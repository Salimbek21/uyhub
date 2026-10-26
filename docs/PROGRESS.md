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
