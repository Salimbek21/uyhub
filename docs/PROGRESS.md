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
| `make test` and `make lint` pass **in CI** | ⚠️ **not verified** — no git remote yet, so the workflow has never executed |

### Known gaps

1. **CI is unverified.** `.github/workflows/ci.yml` is written but has never run. It
   needs a remote and one push. Two specific risks: the digest-pinned MinIO images may
   not be pullable from GitHub's network (they could not be pulled from this one), and
   `astral-sh/setup-uv@v6` / `actions/checkout@v5` major versions are unconfirmed.
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
