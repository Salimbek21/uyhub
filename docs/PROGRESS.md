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
