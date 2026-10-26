# UyHub

Telegram real-estate aggregator for Tashkent. Collects house and apartment listings
(sale and rent) from public Telegram groups and channels, turns messy free-text posts
into structured data, merges duplicates, and serves the result through a Telegram
Mini App, a bot, and an auto-posting channel.

- Product and technical specification: [`docs/SPEC.md`](docs/SPEC.md)
- Working agreement for contributors and agents: [`CLAUDE.md`](CLAUDE.md)
- Current status and how to run what exists: [`docs/PROGRESS.md`](docs/PROGRESS.md)
- Operational procedures: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)
- Architecture decisions: [`docs/DECISIONS.md`](docs/DECISIONS.md)
- Unresolved spec questions: [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md)

## Status

Phase 0 (Foundation). Infrastructure, tooling and CI only — no data model, no
collector, no parser yet. See `docs/PROGRESS.md` for the phase-by-phase state.

## Quick start

Requirements: Docker with the Compose plugin, [uv](https://docs.astral.sh/uv/), GNU Make.

```bash
cp .env.example .env     # then edit the values that matter for your machine
make up                  # Postgres, Redis, MinIO
make migrate             # apply Alembic migrations
make test                # unit + integration tests
make lint                # ruff, mypy --strict (+ frontend from Phase 5)
```

`make help` lists every target, including the ones that are not implemented yet and
the phase that will deliver them.

## Layout

```
backend/     Python package `uyhub` — one package, several entrypoints
  src/uyhub/
    core/    config, logging, db, redis, s3, metrics, clock
    api/     FastAPI application
    cli.py   Typer CLI — every service entrypoint and admin command
  migrations/  Alembic
  tests/       unit/ integration/
infra/       docker-compose files, Caddy config, backup scripts
miniapp/     React + TypeScript Mini App (Phase 5)
docs/        specification and operational documentation
```

## License

Proprietary. All rights reserved.
