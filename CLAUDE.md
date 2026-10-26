# UyHub — Telegram real-estate aggregator

## What this project is
UyHub collects house/apartment listings (sale and rent) that people post in many Telegram groups and channels in Uzbekistan (MVP: Tashkent city only), turns messy free-text posts into structured data, merges duplicates (the same flat is cross-posted to 10+ groups), and serves the result through:
1. a Telegram Mini App (search + filters),
2. a Telegram bot (saved-search notifications, admin commands),
3. an auto-posting Telegram channel.

The full product and technical specification is in `docs/SPEC.md`. Read it before starting any phase. If this file and the spec disagree, the spec wins; tell me about the conflict.

## How we work together
- Work strictly phase by phase as defined in `docs/SPEC.md` section 17. Do not start the next phase until the current phase's Definition of Done is met and all tests pass.
- At the start of each phase: plan first (plan mode), show me the plan, wait for my approval.
- At the end of each phase: update `docs/PROGRESS.md` (what was built, how to run it, known gaps, next steps) and commit with a Conventional Commit message (`feat(collector): ...`).
- If something is not covered by the spec, pick the simplest production-sound option, record it in `docs/DECISIONS.md` (context / decision / consequences) and keep going. Ask me only for decisions that are expensive to reverse: data model shape, a new paid external service, anything security- or privacy-related.
- Do not guess library APIs (Telethon, aiogram, Anthropic SDK, Telegram WebApp). Read the installed package source or official docs when unsure.
- Keep `docs/RUNBOOK.md` current: how to deploy, rotate secrets, restore a backup, re-login the userbot, add a source.

## Stack (changes require an entry in DECISIONS.md)
- Backend: Python 3.12, `uv`, FastAPI, SQLAlchemy 2.0 async + Alembic, Pydantic v2 + pydantic-settings, structlog
- Data: PostgreSQL 16, Redis 7 (Streams for queues), MinIO (S3-compatible) for photos
- Telegram: Telethon (userbot collector), aiogram 3 (bot + channel poster)
- LLM: Anthropic Python SDK, model name from env `LLM_MODEL`
- Mini App: React + TypeScript + Vite, TanStack Query, Tailwind, Telegram WebApp SDK
- Infra: Docker Compose, Caddy (TLS reverse proxy), GitHub Actions, Prometheus metrics, Sentry

## Commands (create in Phase 0, keep this list accurate)
- `make up` / `make down` — local stack
- `make test` — backend tests (unit + integration)
- `make lint` — ruff, mypy --strict, eslint, tsc
- `make migrate` — apply Alembic migrations
- `make eval-parser` — run parser accuracy evaluation on the golden set
- `make login-userbot` — interactive Telethon login, run by a human only

## Code rules
- Type hints everywhere; `mypy --strict` passes on `backend/src`. Ruff for lint and format.
- All I/O is async. No blocking calls inside event loops (offload CPU work like image hashing to a thread pool).
- Config only through pydantic-settings from environment variables. Every variable is documented in `.env.example` with a safe placeholder.
- Structured JSON logs with `service`, and where relevant `source_id`, `tg_message_id`, `listing_id`. Never log phone numbers, session strings, tokens, API keys or full post text at INFO level or above.
- Every external call (Telegram, Anthropic, S3, CBU rates) has a timeout, retry with exponential backoff and jitter, and sits behind an interface that tests can fake.
- Tests: pytest + pytest-asyncio. Integration tests use real Postgres and Redis in Docker. No test may call real Telegram or the real Anthropic API; use fakes and recorded fixtures.
- Schema changes only through new Alembic migrations. Never edit an applied migration.
- Code, comments, commit messages and docs in English. User-facing text goes through i18n keys with `uz` (Latin) and `ru` translations.
- Prefer boring, readable code over clever code. Small modules, explicit names.

## Hard safety rules
- Never commit secrets. `.env*` (except `.env.example`), `*.session`, session strings and backups are in `.gitignore`.
- Never perform the Telegram userbot login yourself and never ask me to paste login codes or 2FA passwords into the chat. Provide a script that I run in my own terminal.
- The userbot only reads. It must never send messages, react, forward, or join more chats per day than `COLLECTOR_MAX_JOINS_PER_DAY`.
- Never run destructive commands against production data (DROP, TRUNCATE, `docker compose down -v`, deleting volumes or buckets) without asking me first.
