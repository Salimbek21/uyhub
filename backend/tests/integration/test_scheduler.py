"""Periodic jobs and the lifecycle work they drive (SPEC 2.1, 8)."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal

import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uyhub.core.clock import now_utc, today_utc
from uyhub.core.config import Settings, get_settings
from uyhub.core.streams import STREAM_LISTINGS
from uyhub.lifecycle import (
    expire_stale,
    recompute_trust_scores,
    remove_suppressed,
    set_status,
)
from uyhub.models.enums import Currency, DealType, ListingStatus, RawMessageStatus
from uyhub.models.listing import Listing
from uyhub.models.ops import SuppressedPhone
from uyhub.models.telegram import RawMessage, Source
from uyhub.rates.cbu import Rate
from uyhub.rates.store import latest_rate
from uyhub.scheduler.jobs import Job, build_jobs, run_job_once, run_loop

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


class FakeRateProvider:
    """A `RateProvider` that never leaves the process."""

    def __init__(self, rate: Decimal = Decimal(12_000)) -> None:
        self.rate = rate
        self.calls = 0

    async def fetch(self, currency: Currency = Currency.USD) -> Rate:
        self.calls += 1
        return Rate(currency=currency, rate_uzs=self.rate, on_date=today_utc())


async def make_listing(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    deal_type: DealType = DealType.SALE,
    last_seen_days_ago: int = 0,
    phone_hashes: list[str] | None = None,
) -> Listing:
    async with session_factory() as session:
        listing = Listing(
            deal_type=deal_type,
            title="test",
            last_seen_at=now_utc() - timedelta(days=last_seen_days_ago),
            phone_hashes=phone_hashes or [],
        )
        session.add(listing)
        await session.commit()
        await session.refresh(listing)
        return listing


class TestExpiry:
    async def test_a_quiet_sale_listing_expires_after_its_ttl(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        await make_listing(session_factory, last_seen_days_ago=settings.listing_ttl_days_sale + 1)

        async with session_factory() as session:
            expired = await expire_stale(session, redis_client, settings)
            await session.commit()

        assert expired == 1
        async with session_factory() as session:
            listing = (await session.execute(select(Listing))).scalar_one()
        assert listing.status is ListingStatus.EXPIRED

    async def test_rent_expires_sooner_than_sale(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        """A rental still up after two weeks has almost certainly gone."""
        between = settings.listing_ttl_days_rent + 1
        assert between < settings.listing_ttl_days_sale

        await make_listing(session_factory, deal_type=DealType.SALE, last_seen_days_ago=between)
        await make_listing(session_factory, deal_type=DealType.RENT, last_seen_days_ago=between)

        async with session_factory() as session:
            expired = await expire_stale(session, redis_client, settings)
            await session.commit()

        assert expired == 1
        async with session_factory() as session:
            statuses = {
                row.deal_type: row.status
                for row in (await session.execute(select(Listing))).scalars()
            }
        assert statuses[DealType.RENT] is ListingStatus.EXPIRED
        assert statuses[DealType.SALE] is ListingStatus.ACTIVE

    async def test_a_recently_seen_listing_is_left_alone(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        await make_listing(session_factory, last_seen_days_ago=1)

        async with session_factory() as session:
            assert await expire_stale(session, redis_client, settings) == 0

    async def test_expiry_emits_a_status_change(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        await make_listing(session_factory, last_seen_days_ago=settings.listing_ttl_days_sale + 1)
        async with session_factory() as session:
            await expire_stale(session, redis_client, settings)
            await session.commit()

        entries = await redis_client.xrange(STREAM_LISTINGS)
        assert [fields["event"] for _id, fields in entries] == ["status_changed"]
        assert entries[0][1]["status"] == "expired"


class TestSuppression:
    async def test_a_suppressed_phone_removes_its_listings(
        self, session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
    ) -> None:
        """A removal request must reach listings collected before it arrived."""
        phone_hash = "c" * 64
        await make_listing(session_factory, phone_hashes=[phone_hash])

        async with session_factory() as session:
            session.add(SuppressedPhone(phone_hash=phone_hash, reason="seller_request"))
            await session.commit()

        async with session_factory() as session:
            removed = await remove_suppressed(session, redis_client)
            await session.commit()

        assert removed == 1
        async with session_factory() as session:
            listing = (await session.execute(select(Listing))).scalar_one()
        assert listing.status is ListingStatus.REMOVED

    async def test_other_listings_are_untouched(
        self, session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
    ) -> None:
        await make_listing(session_factory, phone_hashes=["d" * 64])
        async with session_factory() as session:
            session.add(SuppressedPhone(phone_hash="e" * 64, reason="spam"))
            await session.commit()

        async with session_factory() as session:
            assert await remove_suppressed(session, redis_client) == 0

    async def test_removal_is_terminal(
        self, session_factory: async_sessionmaker[AsyncSession], redis_client: Redis
    ) -> None:
        """SPEC 8: a listing taken down at the seller's request never returns."""
        listing = await make_listing(session_factory)

        async with session_factory() as session:
            fresh = (await session.execute(select(Listing))).scalar_one()
            await set_status(session, redis_client, fresh, ListingStatus.REMOVED, reason="test")
            moved = await set_status(
                session, redis_client, fresh, ListingStatus.ACTIVE, reason="test"
            )
            await session.commit()

        assert not moved
        assert listing is not None
        async with session_factory() as session:
            assert (
                await session.execute(select(Listing))
            ).scalar_one().status is ListingStatus.REMOVED


class TestTrustScore:
    @staticmethod
    async def _seed(
        session_factory: async_sessionmaker[AsyncSession],
        *,
        chat_id: int,
        total: int,
        every_nth_is_a_listing: int,
    ) -> None:
        async with session_factory() as session:
            source = Source(tg_chat_id=chat_id, username=f"source{abs(chat_id)}")
            listing = Listing(deal_type=DealType.SALE, title="t")
            session.add_all([source, listing])
            await session.commit()
            await session.refresh(source)
            await session.refresh(listing)

            for index in range(total):
                session.add(
                    RawMessage(
                        source_id=source.id,
                        tg_message_id=index,
                        posted_at=now_utc(),
                        text="post",
                        status=RawMessageStatus.PARSED,
                        listing_id=listing.id if index % every_nth_is_a_listing == 0 else None,
                    )
                )
            await session.commit()

    async def test_a_productive_source_scores_by_its_hit_rate(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """OPEN_QUESTIONS B4: the field existed but nothing ever computed it."""
        await self._seed(session_factory, chat_id=-1, total=40, every_nth_is_a_listing=2)

        async with session_factory() as session:
            assert await recompute_trust_scores(session) == 1
            await session.commit()

        async with session_factory() as session:
            scored = (await session.execute(select(Source))).scalar_one()
        assert scored.trust_score == pytest.approx(0.5)

    async def test_a_noisy_source_is_floored_not_zeroed(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        """Even a chat group posts the occasional real listing, and the score
        multiplies into quality, which gates channel posting."""
        from uyhub.lifecycle import TRUST_FLOOR

        await self._seed(session_factory, chat_id=-3, total=40, every_nth_is_a_listing=40)

        async with session_factory() as session:
            await recompute_trust_scores(session)
            await session.commit()

        async with session_factory() as session:
            scored = (await session.execute(select(Source))).scalar_one()
        assert scored.trust_score == pytest.approx(TRUST_FLOOR)

    async def test_a_source_with_no_history_is_not_scored(
        self, session_factory: async_sessionmaker[AsyncSession]
    ) -> None:
        async with session_factory() as session:
            source = Source(tg_chat_id=-2, username="new")
            session.add(source)
            await session.commit()
            await session.refresh(source)
            session.add(
                RawMessage(source_id=source.id, tg_message_id=1, posted_at=now_utc(), text="hi")
            )
            await session.commit()

        async with session_factory() as session:
            assert await recompute_trust_scores(session) == 0


class TestRates:
    async def test_the_rate_job_stores_a_rate(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis,
        settings: Settings,
    ) -> None:
        provider = FakeRateProvider()
        jobs = {
            job.name: job
            for job in build_jobs(
                session_factory=session_factory,
                redis=redis_client,
                settings=settings,
                rate_provider=provider,
            )
        }

        await jobs["rates"].run()

        assert provider.calls == 1
        async with session_factory() as session:
            assert await latest_rate(session) == Decimal(12_000)

    async def test_a_failing_job_does_not_raise(self) -> None:
        """One unreachable external service must not end the scheduler."""

        async def explode() -> int:
            raise RuntimeError("cbu.uz is down")

        await run_job_once(Job("rates", timedelta(hours=6), explode))


class TestLoop:
    async def test_every_job_runs_once_at_startup(self) -> None:
        """A restart is how the scheduler catches up on what it missed."""
        ran: list[str] = []

        def recorder(name: str):  # type: ignore[no-untyped-def]
            async def _run() -> int:
                ran.append(name)
                return 1

            return _run

        jobs = [
            Job("fast", timedelta(seconds=1), recorder("fast")),
            Job("slow", timedelta(days=7), recorder("slow")),
        ]
        stop = asyncio.Event()

        task = asyncio.create_task(run_loop(jobs, stop, tick=0.05))
        await asyncio.sleep(0.12)
        stop.set()
        await asyncio.wait_for(task, timeout=2)

        assert "fast" in ran
        assert "slow" in ran, "a weekly job still runs on the first tick"

    async def test_a_long_interval_job_does_not_run_twice_quickly(self) -> None:
        ran: list[str] = []

        async def _run() -> int:
            ran.append("x")
            return 1

        stop = asyncio.Event()
        task = asyncio.create_task(
            run_loop([Job("rare", timedelta(days=1), _run)], stop, tick=0.05)
        )
        await asyncio.sleep(0.25)
        stop.set()
        await asyncio.wait_for(task, timeout=2)

        assert len(ran) == 1


def test_a_rate_carries_its_date() -> None:
    rate = Rate(currency=Currency.USD, rate_uzs=Decimal(12_000), on_date=date(2026, 10, 29))
    assert rate.on_date.isoformat() == "2026-10-29"
