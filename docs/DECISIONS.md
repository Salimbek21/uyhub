# Architecture decisions

One entry per decision, newest phase last. Format: context, decision, consequences.
Anything not covered by `docs/SPEC.md` is decided here rather than left implicit
(CLAUDE.md, "How we work together").

---

## Phase 0 — Foundation

### 0.1 One package, `src/` layout, six CLI entrypoints

**Context.** SPEC 2.1 defines seven services but one Docker image. Python can expose
several entrypoints from one distribution.

**Decision.** A single `uyhub` package under `backend/src/`, with `cli.py` as the only
entrypoint. The image runs `uyhub <service>`. A `src/` layout is used so tests import
the installed package rather than whatever happens to be in the working directory.

**Consequences.** Shared code (config, logging, db) is written once. Services cannot
drift apart in configuration. A service cannot be deployed without the whole package,
which is acceptable at this scale and simplifies the build.

### 0.2 Empty Alembic baseline

**Context.** Phase 0's Definition of Done includes "Alembic baseline", but every table
belongs to Phase 1.

**Decision.** Revision `0001` creates no tables. It enables `pg_trgm`, which the Phase 4
text filter needs and which requires superuser, so it belongs in a revision that runs
as the owner.

**Consequences.** `alembic upgrade head` is a working, tested command from day one, and
`alembic_version` exists before the first real migration.

### 0.3 The database URL comes only from the environment

**Context.** `alembic.ini` normally carries `sqlalchemy.url`. Two sources of truth for
"which database" is how a migration gets applied to the wrong one.

**Decision.** `migrations/env.py` sets the URL from `Settings`, i.e. from `DATABASE_URL`.
`alembic.ini` leaves it empty.

**Consequences.** Migrations and the application always target the same database. Tests
that need a different database set `DATABASE_URL` rather than editing config.

### 0.4 Flat environment variable names, unknown variables ignored

**Context.** SPEC uses flat names (`TG_API_ID`, `LLM_MODEL`). Phases ship incrementally,
so a developer's `.env` will contain variables that the running phase does not know.

**Decision.** No prefix and no nesting; `Settings` declares only the variables the
current phase uses and sets `extra="ignore"`. `.env.example` documents every variable
the full system will need, grouped by phase.

**Consequences.** One spelling per value, matching the spec. A `.env` prepared for a
later phase does not break an earlier-phase service. The cost is that a typo in a
variable name is silently ignored rather than rejected; the documented example file is
the mitigation.

### 0.5 PII redaction is a logging processor, not a convention

**Context.** CLAUDE.md forbids logging phone numbers, tokens, session strings and full
post text. Relying on every call site to remember this will fail eventually.

**Decision.** `core/logging.py` installs a `redact_sensitive` processor that replaces
values under sensitive keys, masks `+998…` numbers anywhere in any string, and
truncates post-text fields. It applies to third-party logs too, via the stdlib bridge.

**Consequences.** A new logging call cannot leak a phone number by accident. Redaction
costs a dict walk per event, bounded at depth 6. Keys not in `SENSITIVE_KEYS` still get
phone-pattern masking, so the list being incomplete is not a leak.

### 0.6 Separate buckets for originals and derivatives

**Context.** SPEC 9.3 requires `large` and `thumb` to be publicly readable while
originals stay private. SPEC 4.5 and 7.3 put both under `listings/{id}/`.

**Decision.** Two buckets: `uyhub-raw` (private) and `uyhub-media` (anonymous read).

**Consequences.** "Public derivatives, private originals" is one bucket policy instead
of a prefix policy that is easy to get wrong. Media keys change shape relative to the
spec's wording; nothing depends on the old shape yet.

### 0.7 Test isolation by transaction rollback

**Context.** Integration tests must use real Postgres (CLAUDE.md) without being slow or
leaking state between tests.

**Decision.** The test database is dropped, recreated and migrated once per session.
Each test runs inside a transaction that is always rolled back. Redis uses DB 15; S3
tests create a bucket named after the test.

**Consequences.** Fast and isolated. Code under test cannot use its own `commit()` to
make changes visible outside the fixture's transaction, which is the usual constraint
of this pattern and is worth the speed.

### 0.8 Session-scoped fixtures are synchronous

**Context.** `pytest-asyncio` runs async fixtures in the event loop of their scope. A
session-scoped async fixture hands objects bound to one loop to tests running in
another, which fails in confusing ways.

**Decision.** Session-scoped setup (`migrated_database`) is a synchronous fixture that
uses `asyncio.run` internally. Only function-scoped fixtures are async.

**Consequences.** No cross-loop errors. Session setup cannot share a connection pool
with tests, which it does not need to.

### 0.9 Unimplemented Make targets exist and fail loudly

**Context.** CLAUDE.md lists `make eval-parser` and `make login-userbot` under "create
in Phase 0", but they belong to Phases 2 and 1.

**Decision.** The targets exist and exit non-zero with the phase that will deliver them.
`make lint` is split into `lint-backend` and `lint-frontend`; the frontend half prints a
skip notice until `miniapp/` exists.

**Consequences.** The documented command list stays accurate and Phase 0's DoD is
satisfiable. Nobody has to guess whether a missing target is a bug or a phase boundary.

### 0.10 Container images pinned by digest

**Context.** SPEC 15 requires dependency pinning. Tags such as `postgres:16-alpine` are
mutable.

**Decision.** Compose pins every image by `sha256` digest, with the human-readable tag
kept in a comment. Upgrading means pulling the new tag, reading its digest and updating
both.

**Consequences.** Byte-identical infrastructure everywhere. Upgrades are explicit rather
than silent. Discovered incidentally: the stock tags for MinIO could not be pulled from
this network at all, and digest pinning sidesteps the question.

### 0.11 Local host ports use a 1xxxx offset

**Context.** 5432, 6379, 9000 and 9001 were all already in use on the developer machine
by other projects.

**Decision.** Compose publishes 15432, 16379, 19000 and 19001, all bound to 127.0.0.1.

**Consequences.** UyHub runs next to other local stacks. Connection strings in
`.env.example` match. Nothing is reachable off-machine.

### 0.12 `pip-audit` reports, it does not yet block

**Context.** SPEC 15 requires `pip-audit` and `npm audit` in CI but does not say whether
a finding fails the build.

**Decision.** The audit job runs on every PR with `continue-on-error: true`.

**Consequences.** Findings are visible without a transitive advisory blocking unrelated
work. Phase 8's security checklist is where this becomes a gate — that is the task that
has to own triage.

### 0.13 `UV_SYSTEM_CERTS=1` is required on this network

**Context.** This network terminates TLS with its own certificate authority. `uv` ships
its own trust store and failed with `invalid peer certificate: UnknownIssuer`.

**Decision.** The Makefile exports `UV_SYSTEM_CERTS=1` for every `uv` invocation.

**Consequences.** `uv` works behind the corporate proxy. The variable is harmless on
networks that do not intercept TLS, so CI needs no special case. Noted in RUNBOOK.md
because a new developer hits this within a minute.

### 0.14 Dependency version bounds were corrected against the index

**Context.** Upper bounds written from memory were wrong: `typer<0.20` excluded every
release that works with the installed `click`, producing a `DeprecationWarning` that
`filterwarnings = error` correctly turned into a failure.

**Decision.** Bounds are verified against the package index rather than assumed.
`typer>=0.27,<1`.

**Consequences.** Reinforces CLAUDE.md's "do not guess library APIs" — it applies to
version numbers as much as to function signatures. `filterwarnings = ["error"]` stays:
it caught this on the first run.

### 0.15 Bucket creation runs behind a Compose profile

**Context.** `docker compose up -d --wait` treats a container that has exited as a
failed start, even on exit code 0. The one-shot `minio-init` container therefore made
`make up` fail after doing its job correctly.

**Decision.** `minio-init` sits behind the `init` profile so `up --wait` ignores it.
`make up` starts the three long-running services, waits for health, then runs
`compose run --rm minio-init`.

**Consequences.** `make up` is one command with an honest exit code. CI calls `make up`
rather than raw Compose so it exercises the same path, including bucket creation.


---

## Deployment infrastructure (prepared ahead of Phase 8)

Built early because the product owner needs a public HTTPS URL: Telegram refuses to
load a Mini App over plain HTTP, so nothing can be tested inside Telegram until this
exists.

### 8.1 One image, several entrypoints; Caddy is the only exposed service

**Context.** SPEC 2.1 defines seven services behind one image; SPEC 15 wants only the
proxy reachable from the internet.

**Decision.** `backend/Dockerfile` builds one image whose entrypoint is the Typer CLI,
so `docker run … api|collector|parser|…` selects the service. In
`docker-compose.prod.yml` only Caddy publishes ports; Postgres, Redis and MinIO are
reachable solely on the Docker network. Caddy terminates TLS for `app.`, `api.` and
`media.`, and returns 404 for `/metrics`.

**Consequences.** One build, one push, one version across all services. A port cannot
be exposed by accident — it has to be added to Caddy's config, which is reviewed.

### 8.2 One-shot services are always invoked with their profile named

**Context.** `migrate` and `minio-init` sit behind Compose profiles so a plain
`up` does not start them.

**Decision.** `deploy.sh` runs them as `docker compose --profile tools run …` and
`--profile init run …`, never bare.

**Consequences.** This is not stylistic. Compose 2.34 **silently drops a service's
`env_file` when `run` targets a service whose profile is not active**: the container
starts with none of its configuration and falls back to code defaults. Measured
directly — `run` on the profiled service produced zero `env_file` variables, the same
service without `profiles` produced them, and naming the profile fixed it. Without
this, production migrations would have run against the default `localhost` database
URL and failed on the first deploy. Recorded in RUNBOOK 4.5 as well, because anyone
running these commands by hand hits the same trap.

### 8.3 The production env file path is a variable

**Context.** `env_file: ../.env` means the production compose reads whichever `.env`
happens to sit in the repository root. On a developer machine that is the local one,
pointing at `localhost`.

**Decision.** `env_file: ["${UYHUB_ENV_FILE:-../.env}"]`. On the server it resolves to
the single production `.env`; a test run points it elsewhere.

**Consequences.** The production topology can be exercised end to end on a laptop
without a production `.env`, which is how the two bugs above were found. Note the
block-sequence form: `[${VAR:-default}]` in YAML flow style is a parse error.

### 8.4 The Mini App is published into a volume by a one-shot container

**Context.** The Mini App is static files. Caddy serves them; something has to put
them where Caddy can read them.

**Decision.** `miniapp/Dockerfile` builds the bundle and its container copies `dist`
into the `miniapp_dist` volume, then exits. `deploy.sh` runs it after the API is up.

**Consequences.** No Node runtime in production. The copy clears the target first, so
a rollback cannot leave two bundles mixed. Two details that are load-bearing: the
mount point must exist in the image **owned by the runtime user**, or Docker creates
the volume root-owned and the non-root container cannot write to it; and the copy uses
`cp -r`, not `cp -a`, because `-a` implies `-p` and fails trying to chown the mount
point. Both were found by running the container, not by reading it.

### 8.5 Deploy rolls back on a failed smoke test, and never touches volumes

**Context.** SPEC 16 requires rollback on failure.

**Decision.** `deploy.sh` tags the running image as `:rollback` before building,
smoke-tests `/readyz` (not `/healthz`) after starting, and on failure retags and
restarts. No path through the script removes a volume.

**Consequences.** A bad deploy costs the smoke-test timeout rather than an outage.
`/readyz` is the right probe because `/healthz` deliberately touches no dependency —
it would report success against a broken database. Migrations run before the switch,
so a migration failure leaves the previous version serving.
