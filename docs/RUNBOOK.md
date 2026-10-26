# Runbook

Operational procedures. Sections are filled in by the phase that makes them real;
anything marked TBD has no implementation yet, and saying so is more useful than a
procedure nobody has run.

---

## 1. Local development

### First-time setup

```bash
# 1. Tooling
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
# Docker Desktop must be running.

# 2. Configuration
cp .env.example .env
# Edit POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD and S3_SECRET_KEY to local values.
# S3_SECRET_KEY must equal MINIO_ROOT_PASSWORD.
chmod 600 .env

# 3. Dependencies, infrastructure, schema
make install
make up
make migrate

# 4. Verify
make check          # probes Postgres, Redis and MinIO from the application
make test
make lint

# 5. Git hooks (once per clone)
make hooks
```

### Behind a TLS-intercepting network

If `uv` fails with `invalid peer certificate: UnknownIssuer`, it is using its own
trust store instead of the system's. The Makefile already exports `UV_SYSTEM_CERTS=1`
for every `uv` call; for a bare `uv` command, set it yourself:

```bash
UV_SYSTEM_CERTS=1 uv sync
```

Docker Hub may also be unreachable on such a network. Compose pins images by digest, so
an image already in the local cache is used without contacting the registry.

### Host ports

UyHub publishes **15432** (Postgres), **16379** (Redis), **19000** (MinIO API) and
**19001** (MinIO console), all on 127.0.0.1, so it can run alongside other local
stacks. The MinIO console is at <http://localhost:19001>.

### Everyday commands

| Command | What it does |
|---|---|
| `make help` | List every target |
| `make up` / `make down` | Start / stop infrastructure (data is kept) |
| `make logs` | Follow container logs |
| `make test` | Unit and integration tests |
| `make test-unit` | Only tests that need no infrastructure |
| `make lint` | ruff, mypy --strict (plus the Mini App from Phase 5) |
| `make fmt` | Format and autofix |
| `make migrate` | Apply migrations |
| `make migration m="..."` | Create a revision |
| `make db-shell` | psql against the local database |
| `make api` | Run the API with auto-reload |
| `make check` | Probe every external dependency |

### Resetting local data

`make clean-volumes` deletes the Postgres, Redis and MinIO volumes. It asks for
confirmation because the data is unrecoverable. `make clean` only removes tool caches
and touches no data.

---

## 2. Adding a source

TBD — Phase 1. Will be `uyhub sources add <@username | https://t.me/... | invite link>`
or the bot's `/addsource`. New sources enter `pending_join` and the join worker picks
them up within a day, subject to `COLLECTOR_MAX_JOINS_PER_DAY`.

## 3. Re-logging in the userbot

TBD — Phase 1.

Two rules that already apply:

- **A human runs this, never an agent and never CI.** `make login-userbot` is
  interactive: the phone number, the SMS code and the 2FA password are typed into the
  operator's own terminal.
- Those values are never written to a log, a file or a chat. The only artefact is the
  Telethon session file, mode 0600, in a Docker volume.

## 4. Deployment

TBD — Phase 8. Will be: push a tag, CI builds and pushes the image, deploys over SSH,
runs migrations, `docker compose up -d`, smoke-tests `/readyz`, and rolls back to the
previous tag on failure.

## 5. Rotating secrets

TBD — Phase 7/8. Partial notes that already matter:

- `.env` on the server is mode 0600 and exists only there.
- **`PHONE_HASH_KEY` cannot simply be rotated.** Changing it invalidates every
  `listings.phone_hashes` entry and every `suppressed_phones` row, which would
  re-expose listings whose owners asked for removal. See `OPEN_QUESTIONS.md` C8; a
  rotation procedure has to be designed before the key is ever changed.
- Telegram's `api_hash` cannot be rotated at all — a new app registration is the only
  option. It is not account-equivalent: login still requires phone, code and 2FA.

## 6. Backup and restore

TBD — Phase 7. Nightly encrypted `pg_dump`, 14 daily + 8 weekly, second location in
Uzbekistan, plus a weekly MinIO mirror. The restore procedure must be tested, not just
written: Phase 7's DoD requires restoring into a fresh database and running the API
against it.

## 7. Alerts

TBD — Phase 7. Alerts from SPEC 14 are delivered to admins through the bot.

## 8. Incident checklist

TBD — Phase 7. First diagnostics that already work:

```bash
make ps                 # is anything down?
make check              # can the application reach its dependencies?
curl localhost:8000/readyz | jq   # which dependency is failing
make logs               # recent container logs
```
