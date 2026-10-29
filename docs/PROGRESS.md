# Progress

One entry per phase. See `docs/SPEC.md` section 17 for the phase definitions.

---

## Phase 0 — Foundation ✅

Completed 2026-10-26.

### What was built

**Repository.** Git repository initialised on `main`. `.gitignore` protects `.env*`
(except the example), `*.session`, backups and `.DS_Store`. `.editorconfig`, `README.md`.

**Python project.** `backend/` as a `uv` project on Python 3.12.15, `src/` layout,
`uv.lock` committed. Phase 0 dependencies only — later phases add their own.

**Package skeleton** (`backend/src/uyhub/`):

| Module | Contents |
|---|---|
| `cli.py` | Typer CLI: `collector`, `parser`, `api`, `bot`, `poster`, `scheduler`, plus `version`, `check`, `init-storage` |
| `core/config.py` | `Settings` from environment variables, password-masking properties, async-driver validation |
| `core/logging.py` | structlog JSON logging with a PII-redaction processor and a stdlib bridge |
| `core/db.py` | Async engine, session factory, `session_scope()`, readiness probe |
| `core/redis.py` | Async client and readiness probe |
| `core/s3.py` | aioboto3 client, bucket creation, readiness probe |
| `core/metrics.py` | Prometheus registry and `/metrics` ASGI app |
| `core/clock.py` | `now_utc()` so time is injectable |
| `core/errors.py` | `UyHubError`, `ConfigError`, `DependencyUnavailableError` |
| `models/base.py` | Declarative base with a constraint naming convention, `TimestampMixin` |
| `api/app.py` | FastAPI with `/healthz`, `/readyz`, `/metrics` |
| `service.py` | SIGTERM-aware service loop shared by every long-running entrypoint |

**Infrastructure.** `infra/docker-compose.yml` with Postgres 16.15, Redis 7.4.11 and
MinIO, every image pinned by digest, healthchecks on all three, plus a one-shot
`minio-init` that creates `uyhub-raw` (private) and `uyhub-media` (public read).
Ports 15432 / 16379 / 19000 / 19001, bound to 127.0.0.1.

**Migrations.** Alembic on the async template. The URL comes from `DATABASE_URL`, never
from `alembic.ini`. Revision `0001` is an intentionally empty baseline that enables
`pg_trgm`.

**Tests.** 78 tests, all passing. Fixtures for Postgres (session-scoped drop/create/
migrate, per-test transaction rollback), Redis (DB 15) and S3 (per-test bucket).
Coverage: settings validation and secret masking, log redaction (phones in fields, in
free text and in nested structures; sensitive keys; post-text truncation; the stdlib
bridge), liveness and readiness including failure paths, live Postgres/Redis/MinIO
round-trips, Redis Streams with consumer groups, `pg_trgm`, and migration
upgrade/downgrade/offline-SQL.

**Quality gates.** ruff (lint + format, including bandit, flake8-async and
flake8-datetimez rules), `mypy --strict` clean on `backend/src`, pre-commit with
gitleaks and a hook that refuses to commit `.env` or `*.session`, and a GitHub Actions
workflow running lint, types, tests against real infrastructure, and a dependency audit.

**Documentation.** `.env.example` documenting every variable the full system will need,
grouped by phase. `DECISIONS.md` (15 entries), `OPEN_QUESTIONS.md` (28 spec findings),
`RUNBOOK.md`, `PRIVACY.md` and `SECURITY_CHECKLIST.md` skeletons.

### How to run it

```bash
cp .env.example .env    # then set the three passwords
make install && make up && make migrate
make test && make lint
make api                # http://127.0.0.1:8000/healthz
```

Full instructions, including the TLS-proxy and port notes, are in `RUNBOOK.md`.

### Definition of Done

| Criterion | Status |
|---|---|
| `make up` brings up healthy infrastructure | ✅ all three containers healthy, buckets created |
| `make test` passes locally | ✅ 78 passed |
| `make lint` passes locally | ✅ ruff + `mypy --strict` clean |
| `make test` and `make lint` pass **in CI** | ✅ since 2026-10-27 — see the Phase 1 entry; the first run failed exactly as gap 1 below predicted |

### Known gaps

1. ~~**CI is unverified.**~~ **Closed 2026-10-27.** The prediction was right: the first
   run failed on the MinIO images, though for a worse reason than a blocked network —
   MinIO had withdrawn them everywhere. SeaweedFS replaced it (DECISIONS 1.0). The
   action versions turned out to be fine.
2. **No application container.** Phase 0 runs the app on the host; the `Dockerfile`
   arrives in Phase 1 with the first real service.
3. **No tables.** The data model is Phase 1. The baseline migration is empty by design.
4. **Services are stubs.** `collector`, `parser`, `bot`, `poster` and `scheduler` start,
   log, idle and shut down cleanly on SIGTERM. That is the whole contract so far.
5. **No Sentry wiring.** `SENTRY_DSN` is read but unused pending `OPEN_QUESTIONS.md` A6.
6. **`npm audit` and the Mini App CI job** are guarded no-ops until Phase 5.

### Next steps

Phase 1 — Data model and collector. Before starting, two items from
`OPEN_QUESTIONS.md` need a decision from the product owner:

- **A3** — 5 joins/day against 50–200 sources is a 10–40 day ramp. Slow ramp, more
  accounts, or a prioritised first batch?
- **C1** — the legal basis for storing scraped phone numbers. SPEC 13 defers to a
  lawyer but no phase schedules it; it should land before Phase 6 ships contact reveal.

Phase 1 also needs from the human (SPEC 18): a dedicated SIM for the userbot and the
list of initial test sources. `TG_API_ID` and `TG_API_HASH` were supplied on 2026-10-26
and are in the local `.env`.

---

## UI prototype (out of phase order) ✅

Completed 2026-10-26, at the product owner's request so the product could be seen and
reacted to before four more phases of backend work.

### What was built

`miniapp/` — the real Phase 5 project, not a throwaway mock: React 19, TypeScript,
Vite 7, Tailwind 4, TanStack Query 5, hand-typed Telegram WebApp SDK wrapper.

| Area | Contents |
|---|---|
| `src/types.ts` | The API contract, mirroring SPEC 9.2 response shapes |
| `src/data/client.ts` | **The only file that knows where data comes from.** One function per endpoint, with simulated latency. Phase 4 swaps the bodies for `fetch` and no screen changes |
| `src/data/listings.ts` | 24 listings written in the style the parser should produce: generated uz titles, cleaned descriptions, canonical districts, USD and UZS prices, 1–3 sources each, two with price drops |
| `src/telegram.ts` | Theme params, BackButton, MainButton, haptics, `openTelegramLink` — all guarded so the app runs in a plain browser |
| `src/i18n/` | Uzbek Latin and Russian, with price and relative-time formatting |
| `src/screens/` | Feed, Detail, Favorites, Saved searches, Settings |
| `src/components/` | Filter sheet, listing card, swipe gallery, tab bar, skeletons, empty and error states |

Working: quick filter chips, full filter sheet with a live match count on the Apply
button, infinite scroll, favourites (persisted), saved searches, photo gallery with
swipe, price-drop indicator, source attribution links, phone reveal behind a separate
call, uz/ru switching, light and dark themes, 360 px layouts.

### Verified by running it

- `npm run lint`, `npx tsc --noEmit`, `npm run build` all clean; bundle 97 kB gzipped
- Driven in a 430×932 browser window: feed, language switch, filter sheet
  (count 13 → 2 on Chilonzor + 3 rooms), detail, phone reveal, empty favourites
- Console clean — zero errors, zero warnings
- Dark theme verified by forcing `data-theme="dark"`

### Known gaps

1. **Photos are drawn placeholders**, not photographs — inline SVG rendered by
   `components/Photo.tsx`, deliberately not `data:` URIs (those break under a strict
   `img-src` CSP and in older WebViews). The component shows an `<img>` as soon as a
   real URL exists, so Phase 1's MinIO images need no screen changes.
2. **Favourites and saved searches live in `localStorage`**, not on the server. Phase 4
   moves them to the `favorites` and `saved_searches` tables.
3. **Not yet opened inside a real Telegram client.** That needs an HTTPS tunnel and a
   bot from @BotFather (Phase 6 inputs). The SDK integration is written and guarded but
   only exercised in a browser, so BackButton, MainButton and haptics are untested in
   situ.
4. **No deep linking.** Navigation is local state; the `start_param` entry point that
   opens a specific listing from a bot notification is Phase 5 work.
5. **No tests.** The prototype is for looking at and reacting to. Phase 5 adds the
   component and interaction tests, and Lighthouse ≥ 80 per its DoD.
6. **Russian UI shows Uzbek listing titles** — see `OPEN_QUESTIONS.md` B11.

### How to run it

```bash
cd miniapp && npm install && npm run dev   # http://127.0.0.1:5173
```

---

## Phase 1 — Data model and collector ✅

Completed 2026-10-27.

Four product decisions were taken before starting and are recorded in
`DECISIONS.md` under "Product direction": build a vertical slice to production
first (P.1), never store or serve phone numbers in plaintext (P.2), curate the
first thirty sources by priority (P.3), ship the parser regex-first (P.4). P.2
and P.3 close OPEN_QUESTIONS C1, C2 and A3.

### What was built

**Data model.** All fourteen tables from SPEC section 3, as five modules:
`models/telegram.py` (tg_accounts, sources, raw_messages), `models/listing.py`
(listings, listing_sources, listing_photos, price_history), `models/user.py`
(users, favorites, saved_searches, notification_log), `models/ops.py`
(suppressed_phones, llm_calls, exchange_rates), plus `models/enums.py` and the
`IdMixin` / `UuidMixin` / `enum_column` helpers in `models/base.py`.

Two deliberate departures from SPEC 3, both from P.2: there is no
`contact_reveals` table and `listings` has no plaintext `phones` column, only
`phone_hashes`. One addition: `sources.priority` for P.3.

**Migration `0002`** creates all of it, including the indexes the rest of the
system depends on — `(status, deal_type, district, rooms, price_usd)`,
`(status, first_seen_at DESC)`, GIN on `phone_hashes`, trigram GIN on `title`
and `landmark`, and `(status, priority)` for the join worker. `alembic check`
passes, so models and migration cannot drift apart silently.

**Redis Streams** (`core/streams.py`): publish with `MAXLEN ~` trimming,
consumer groups, `XAUTOCLAIM` for messages stranded by a dead consumer, and a
dead-letter path to `stream:dead`.

**Collector** (`collector/`, nine modules):

| Module | Contents |
|---|---|
| `types.py` | `IncomingMessage`, `IncomingMedia`, `DeletedMessages`, `ResolvedChat` — plain dataclasses, no Telethon |
| `gateway.py` | The only module importing Telethon. `TelegramGateway` Protocol + `TelethonGateway`; album folding; media description |
| `client.py` | Client construction from settings; warns if the session file is group- or world-readable |
| `ingest.py` | `MessageIngestor` — upsert into `raw_messages`, photos to object storage, publish to `stream:raw`, mark deletions |
| `media.py` | `PhotoStore` Protocol + `S3PhotoStore`; keys are `raw/{source_id}/{tg_message_id}/{n}.jpg` |
| `sources.py` | Reference parsing (`@name`, `t.me/...`, invite links), CRUD, the active-chat map, the high-water mark |
| `accounts.py` | Phone masking, the daily join budget under `FOR UPDATE`, flood-wait state |
| `joiner.py` | `JoinWorker` — priority order, budget, 10–40 minute jitter, join → backfill → active |
| `backfill.py` | Gap recovery (forward from `last_message_id`) and first-join history (last `COLLECTOR_BACKFILL_DAYS` days) |
| `heartbeat.py` | `collector:heartbeat:{account_id}`, 30 s interval, 90 s TTL |
| `runner.py` | `SourceRegistry` (pub/sub + 60 s fallback), event routing, bounded concurrency, flood-wait handling, drain on SIGTERM |
| `bootstrap.py` | Assembles the above from `Settings` |

**CLI.** `uyhub collector` runs the real loop. New `uyhub sources
add|list|pause|resume|remove` group; every change publishes `sources:changed` so
a running collector reloads without a restart.

**Operator script.** `backend/scripts/login_userbot.py` behind `make
login-userbot` — interactive, human-only, writes the session at 0600 and
registers the account keeping only the last four digits of the phone.

**Production.** The `collector` service is live in `docker-compose.prod.yml`
(one replica, `backend_data` volume for the session). `deploy.sh` starts it only
when a session file exists and prints what to do when it does not.

**Object storage moved from MinIO to SeaweedFS.** The first CI run — the first ever,
since Phase 0 had no remote — failed at `make up`: MinIO has withdrawn its community
images from Docker Hub, quay.io and `dl.min.io`, and the stack only still worked here
because of a 13-month-old local image cache. SeaweedFS 4.51 replaced it with no
application code change; see DECISIONS 1.0. This also closes Phase 0's known gap 1.

### Verified

- `make test` — **193 passed** (was 78), against SeaweedFS
- `make lint` — ruff, `mypy --strict`, eslint, tsc all clean
- `alembic upgrade head` → `downgrade 0001` → `upgrade head` round-trips
- `uyhub sources add/list` driven against the real local database

New tests, 115 of them, concentrated where the DoD asks:

| Area | Covers |
|---|---|
| `unit/test_collector_gateway.py` | Album folding incl. caption not on the first message and out-of-order ids; adjacent albums not merged; media classification; emptiness; `out`; invite-hash parsing; that `raw` carries no sender details |
| `unit/test_collector_sources.py` | Every reference form, and that `t.me/joinchat/x` is not read as a username |
| `unit/test_config.py` | Phase 1 settings, `TG_API_HASH` absent from `repr`, join budget bounds |
| `integration/test_collector_ingest.py` | New messages, albums, the 10-photo cap, undownloadable photos, videos, edits resetting `parsed` → `pending`, redelivery staying silent, deletions, gap recovery not duplicating, first-join backfill bounded by age |
| `integration/test_collector_joiner.py` | Priority order, budget exhaustion and daily reset, `FloodWaitError` parking the account, `ChannelPrivateError` parking the source, backfill on join |
| `integration/test_collector_runner.py` | Registry filtering, newly activated sources, deletion with no chat id, a failing ingest not killing the service, drain finishing in-flight work |
| `integration/test_streams.py` | Groups, pending, ack, `XAUTOCLAIM`, dead-letter |
| `integration/test_schema.py` | Every table present, `contact_reveals` absent, no `phones` column, each required index and its access method |

Two bugs were found by these tests rather than in review: `sa.Enum(native_enum=False)`
does **not** create a `CHECK` constraint without `create_constraint=True`, so
every enum column was an unchecked `VARCHAR`; and the `db_session` fixture needed
`join_transaction_mode="create_savepoint"` before a test could provoke an
`IntegrityError` without breaking the fixture's own transaction.

### Known gaps

1. **Never run against real Telegram.** No SIM has been logged in yet, so the
   DoD's manual check — post in a test source, see it in `raw_messages` within
   5 s — is outstanding. This is the next thing that needs the product owner
   (OPEN_QUESTIONS A8 accepted this split).
2. **`raw_messages` is written but nothing reads it.** The parser is Phase 2;
   `stream:raw` accumulates until then, bounded by `MAXLEN ~ 100000`.
3. **One account only.** The schema and the budget logic are per account, and
   `sources.account_id` exists, but a second account has never been exercised
   (OPEN_QUESTIONS C3).
4. **No collector metrics.** Prometheus counters are Phase 7; today the signals
   are the heartbeat key, `sources.messages_total` and the logs.
5. **Deletions in small groups cannot be attributed.** Telegram does not say
   which chat, so they are counted and dropped (SPEC 4.3 says as much).
6. **The album handler trusts Telethon's own album assembly.** `events.Album`
   batches by a short timer; a photo arriving unusually late would be ingested
   as a separate row. Gap recovery would not fix it, because the row exists.

### Next steps

Phase 2 — parser, regex-first per DECISIONS P.4. Needed from the product owner
before the manual DoD check can be ticked: the userbot SIM logged in, and three
to five test sources.

---

## Phase 2 — Parser ✅ (regex stage)

Completed 2026-10-28. Built regex-first per DECISIONS P.4; the LLM extractor
slots in behind the same interface when `ANTHROPIC_API_KEY` arrives.

### What was built

**Data files, not code** (`parser/data/`) — SPEC 5.1 is explicit that the
keyword lists live outside the source. Three keyword files (Uzbek Latin, Uzbek
Cyrillic, Russian), a stopword file, and `districts.yaml` with the twelve
districts, their aliases in every script and spelling, and the landmarks that
identify a district on their own.

**The parser** (`parser/`, nine modules):

| Module | Contents |
|---|---|
| `schema.py` | `RawExtraction` (what an extractor claims, SPEC 6.2) and `Extraction` (what gets stored, after 6.3). Two models so the eval can score an extractor without normalisation flattering it |
| `prefilter.py` | SPEC 5.1 rejection, with the reason counted. Stopwords beat signals; a short question with no price is conversation |
| `regex_extract.py` | Prices in every written form, `R/F/T`, rooms spelled or labelled, floors, area, sotix, negotiable, and the keyword-driven categories |
| `districts.py` | Loading `districts.yaml`, folding text for matching, and refusing to guess when two districts are named |
| `extractor.py` | `Extractor` protocol + `RegexExtractor`; infers the deal type from the price when the post names no verb |
| `normalize.py` | USD conversion, SPEC 6.3 sanity rules → `needs_review` with reasons, description cleaning, `quality_score`, Uzbek title |
| `pipeline.py` | `parse()` — prefilter → extract → normalise as one **pure function**, which is what lets the eval run the real pipeline |
| `runner.py` | The worker: consume `stream:raw`, parse, write back, ack; dead-letter after five deliveries |
| `reparse.py` | Re-queue stored messages so one code path still does the writing |

**Supporting:** `core/phones.py` (E.164 + keyed HMAC, and telling a phone from
a price), `rates/` (CBU client behind a protocol + store), migration `0003`
adding `raw_messages.extracted`.

**CLI:** `uyhub parser`, `uyhub reparse --since/--version-below`,
`uyhub update-rates`. **Production:** the `parser` service is live in the prod
compose at one replica (two race on the merge path until Phase 3's advisory
lock — OPEN_QUESTIONS C5), and `deploy.sh` refreshes the rate before starting.

**Golden set and eval:** 159 posts across seven JSONL files, and
`make eval-parser`, which CI now gates on.

### Verified

- `make test` — **455 passed** (was 193)
- `make lint` — ruff, `mypy --strict`, eslint, tsc clean
- `uyhub update-rates` against the real CBU API: `USD 11861.96 on 2026-10-27`
- `make eval-parser` — 159 posts, 100% rejection precision, 100% listing recall

### The accuracy number, honestly

`make eval-parser` reports **100% on all five SPEC 1.5 fields**. That is not an
accuracy measurement and must not be quoted as one.

The golden set is synthetic, and the parser was tuned against it in the same
sitting — the exact failure OPEN_QUESTIONS C4 describes. Every mistake the first
run surfaced was fixed by changing the parser (Russian declensions, labelled
lists, a newline welding a number to the next label, the `k` multiplier matching
the `k` in `75 kv`) or by correcting a fixture that asserted something its own
text did not say. Both are legitimate; neither makes 100% meaningful.

The real figure arrives when the userbot is logged in and real anonymised posts
replace the synthetic ones. CI gates at 90% today purely to catch regressions.

### First contact with real data — 2026-10-28

The userbot was logged in and the collector joined its first real source,
`KVARTIRA TOSHKENT ARENDA IJARA`, backfilling **47 posts**. Running the parser
over them found three things no amount of synthetic fixtures would have:

| What broke | Why | Result |
|---|---|---|
| 23 of 47 posts rejected as `multi_listing` | The heuristic keyed on two phones + two prices. Real realtor posts write `TEL. x / y` and `Narx: 1400$ _ 1200$ Ga Oberladi` — two numbers, one flat | Re-keyed on two different **room counts**; 23 parsed → 46 |
| 44 of 46 listings had no `deal_type` | These posts contain no verb at all. The price rule only inferred *sale*, above the floor | Price now decides both ways; 45 of 46 read as `rent`, matching the channel |
| The parser died on an empty queue | `TimeoutError` — the blocking stream read and the Redis socket timeout were both 5 s | The block is capped below the socket timeout, asserted by a test |

Field coverage on those 46 posts afterwards: `deal_type` 45, `rooms` 43,
`price_usd` 43, `floor` 43, `property_type` 40, `district` 35, `area_m2` 3.
Area is low because this source simply does not state it — a format fact, not a
parser bug.

Every one of these is now a regression test in
`tests/unit/test_parser_pipeline.py::TestRealPostFormats`, kept separate from
the synthetic fixtures because it is the only part of the suite that is evidence
rather than invention.

### Known gaps

1. **One source, 47 posts, one day.** The corrections above are real but the
   sample is one channel's house style. The second source is queued and the
   join worker picks it up on its own schedule.
2. **No LLM extractor.** `LLM_ENABLED=true` raises rather than silently running
   the regex one. Complex posts — ones that bury the price in a sentence, or
   describe the property in prose — are where the gap will show.
3. **Multi-listing detection is a heuristic** needing two phones *and* two
   prices. It will miss some; the counter measures how many (C7).
4. **Nothing reads `raw_messages.extracted` yet.** Listings are Phase 3, so the
   Mini App still shows mock data — the 46 parsed posts are in the database but
   not visible to anyone.
5. **One parser replica.** Two would race on the merge path; the advisory lock
   that makes a second safe is Phase 3 (C5).
6. **Landline numbers are not collected** — `71` collides with too many prices
   to match without an explicit `+998` (DECISIONS 2.2).

### Next steps

Phase 3 — dedup, media processing and the listing lifecycle. That is the step
that first produces rows in `listings`, and therefore the first point at which
the Mini App can show something real.

---

## Phase 3 — Dedup, media and lifecycle ✅

Completed 2026-10-29. **The first step that writes to `listings`.**

Eight decisions were taken and are written up in `DECISIONS.md` 3.1–3.8;
between them they close OPEN_QUESTIONS B1, B2, B3, B4, B9 and C5.

### What was built

**`media/`** — `phash.py` computes a 64-bit perceptual hash in forty lines of
Pillow and numpy rather than pulling scipy and PyWavelets in behind
`imagehash` (3.2). `process.py` turns an original into a 1280px `large` and a
400px `thumb` webp with EXIF stripped, and is deliberately split into a pure
function over bytes and a separate storage step — dedup needs the hash before
it knows which listing the photo belongs to.

**`dedup/`** — `fingerprint.py` (the exact key and a SimHash, both on blake2b
so they survive a restart), `matcher.py` (SPEC 7.1's four rules in order),
`merge.py` (fill-never-overwrite, price history, photo dedup by sha256) and
`assemble.py`, the orchestrator.

**`lifecycle.py`** — the four states and their transitions, including the rule
that a deleted post does not retire a listing until every source has dropped it
*and* three days have passed. Deleting and reposting is how these groups bump a
listing; acting on the first deletion would retire half the feed every evening.

**`scheduler/`** — `uyhub scheduler` was an empty loop; it now runs four jobs
(rates, suppressions, expiry, trust scores), each once at startup so a restart
is a catch-up, and none of which can take the service down.

**Wiring.** The parser worker now assembles after it parses, in the same
transaction. `scheduler` is live in the prod compose; `parser` still runs one
replica until a second is measured rather than assumed.

### Verified

- `make test` — **527 passed** (was 455)
- `make lint` — ruff, `mypy --strict`, eslint, tsc clean
- The five scenarios SPEC's Phase 3 DoD names, each end to end against real
  Postgres, Redis and object storage

| Scenario | Result |
|---|---|
| The same flat in five groups | 1 listing, 5 attributions, `created` then four `updated` |
| One realtor, three different flats | 3 listings — the negative case that matters most |
| A repost at a lower price | 1 listing, a `price_history` row, version bumped |
| An edit saying "sotildi" | `sold`, `status_changed` emitted |
| Deleted and reposted | fresh deletion ignored; an old one with every source gone expires |

Plus: the same photo from five groups stored once, reprocessing a message
updating rather than duplicating, a suppressed seller never getting a listing,
and a terser repost never erasing a known field.

End to end on live data: **120 collected posts → 27 listings from 105
attributions** (3.89 posts per listing), photos readable anonymously from the
public bucket while the originals stay private.

### What looking at the output found

Both of these passed every test and were only visible once the listings were
rendered side by side — worth recording because fixtures would not have caught
either.

1. **Stale titles.** The title is derived from the type, rooms and district,
   but was built once at creation. A listing born from a terse post kept
   "3 xonali obyekt" long after a later sighting established it was a flat in
   Chilonzor. `merge_fields` now rebuilds the title when any of its inputs is
   filled.
2. **A guess stored as a fact.** `property_type` was not nullable and defaulted
   to `apartment`, so 14 posts that never named a type were filed as flats —
   and, being non-null, could never be corrected by a later sighting. Now
   `other`, correctable, and inferred from the floor pair where the post gives
   one (DECISIONS 3.8).

### Known gaps

1. **Nothing reads `listings` yet.** The API is Phase 4, so the Mini App still
   shows mock data even though the table is now populated.
2. **One parser replica.** The advisory lock makes a second safe in principle;
   it has not been run.
3. **Dedup is unmeasured on scale.** The rules are right on fixtures and on one
   source's real posts. The duplicate rate SPEC 1.5 asks about (<5%) needs
   several sources and a manual sample of a hundred listings.
4. **Backfill is still slow** — photos download sequentially while live
   ingestion is concurrent. Noticeable on a first join, harmless afterwards.
5. **Rule 4 scans candidates in Python.** Narrowed by deal type, room count and
   the lookback window, and capped at 200 rows with a warning when hit, but
   Hamming distance over a bigint is not something Postgres can index. Worth
   revisiting if the candidate-limit warning ever appears.

### Next steps

Phase 4 — the API. `/v1/listings` with filters and cursor pagination, plus
`initData` authentication, which is the first thing that needs a `BOT_TOKEN`
from the product owner.
