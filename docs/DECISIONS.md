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

## Product direction (2026-10-27)

### P.1 Build a vertical slice to production, then fill it in

**Context.** The product owner asked for a working product in production. SPEC 17
sequences eight phases and puts anything user-visible behind five of them.

**Decision.** Build the shortest end-to-end chain first — collector → parser →
dedup → API → Mini App, deployed on the VPS — and defer the bot, the channel
poster and the operations phase until real listings are flowing. Phase order
within the slice still follows SPEC 17; what moved is Phases 6 and 7.

**Consequences.** Real posts become visible weeks earlier, which is what makes
the parser measurable against real data instead of synthetic fixtures. The cost
is that production runs for a while without alerting or backups, so the first
weeks are explicitly a supervised pilot, not a launch.

### P.2 Phone numbers are never stored in plaintext and never served

**Context.** OPEN_QUESTIONS C1: SPEC 13 says where phone numbers live but not
whether harvesting sellers' numbers from third-party groups and republishing
them is lawful. SPEC 9.2 specifies a `POST /listings/{id}/contact` endpoint and
SPEC 3 a `contact_reveals` audit table.

**Decision.** Store only `phone_hashes` (keyed HMAC), which is all that dedup
needs. Do not add a `phones` column, the contact endpoint, or the
`contact_reveals` table. The Mini App sends the user to the original Telegram
post via `listing_sources.tg_link`.

**Consequences.** The highest-impact legal exposure is removed, and the product
barely changes: the seller is one tap away either way, in the chat where they
chose to publish. `raw_messages.text` still holds the original post for its
90-day retention, so a future decision to show numbers is a reparse, not a data
loss. SPEC 9.2, SPEC 3 and the Mini App's `revealContact` stub are superseded.

### P.3 The first thirty sources are curated and join first

**Context.** OPEN_QUESTIONS A3: five joins per day per account against 50–200
sources is a 10–40 day ramp, and SPEC 1.3 expects the full list in the MVP.

**Decision.** `sources.priority` (smallint, default 100, lowest first) orders the
join queue. The curated first batch gets 1–30 and is live in about six days; the
rest trickle in behind it.

**Consequences.** Useful inventory in under a week without raising the join rate,
which is the thing that gets accounts banned. The join worker's query is a single
index scan on `(status, priority)`.

### P.4 The parser ships regex-first, with the LLM behind an interface

**Context.** `ANTHROPIC_API_KEY` is not available yet, and SPEC 6 makes the LLM
the primary extractor.

**Decision.** Phase 2 implements SPEC 5 (prefilter and regex extraction) behind
an `ExtractorProtocol`, with the LLM extractor added as a second implementation
when the key arrives.

**Consequences.** The full chain runs and can be measured without an API key, and
the switch is one setting rather than a rewrite. Accuracy on complex posts will
be visibly lower until the LLM is enabled; the eval script is what makes that
difference a number rather than an opinion.

---

## Phase 1 — Data model and collector

### 1.1 Enum columns are `VARCHAR` + `CHECK`, not native PostgreSQL enums

**Context.** SPEC 3 defines fourteen enumerated columns. Native PostgreSQL enums
need `ALTER TYPE` to gain a value, which cannot run in a transaction alongside
other DDL.

**Decision.** `models/base.enum_column()` wraps `sa.Enum(..., native_enum=False,
create_constraint=True, values_callable=...)`.

**Consequences.** Adding a district or a property type is an ordinary migration.
`create_constraint=True` is **not** the SQLAlchemy default and is the whole point
of the helper — without it the column is an unchecked `VARCHAR`; a test writes an
invalid value and asserts the database rejects it. `values_callable` stores the
string values rather than the Python member names, so the database matches the
API.

### 1.2 All of SPEC section 3 in one migration

**Context.** The fourteen tables form one connected foreign-key graph.

**Decision.** Migration `0002` creates all of them. `contact_reveals` is omitted
(P.2), and `listings` has no plaintext `phones` column.

**Consequences.** No intermediate schema state exists that any code was ever
written against. `alembic check` passes, so models and migration cannot drift
silently.

### 1.3 Telethon is confined to one module behind a Protocol

**Context.** CLAUDE.md requires every external call to sit behind an interface
tests can fake, and forbids tests from touching real Telegram. Telethon ships no
`py.typed`, so `mypy --strict` cannot see into it.

**Decision.** `collector/gateway.py` is the only module that imports Telethon. It
defines a `TelegramGateway` Protocol over normalised dataclasses
(`IncomingMessage`, `DeletedMessages`, `ResolvedChat`) and a `TelethonGateway`
implementation. `tests/fakes.py` provides an in-memory `FakeGateway`.
`pyproject.toml` scopes `ignore_missing_imports` to `telethon.*` alone.

**Consequences.** Albums, edits, deletions, gap recovery and flood waits are all
tested end to end with no network and no mocking library. The untyped third-party
surface is one file rather than the whole collector. The Protocol has no method
that sends, forwards or reacts, so the read-only rule is structural rather than a
convention.

### 1.4 Ingestion is idempotent by upsert, and silent when nothing changed

**Context.** Redis Streams deliver at least once (SPEC 2.3), backfill overlaps
live handlers by design (SPEC 4.4), and an edit must make the parser look again
(SPEC 4.3).

**Decision.** `(source_id, tg_message_id)` is unique;
`MessageIngestor._upsert` does `ON CONFLICT DO UPDATE` and returns whether
anything actually changed. Only a real change publishes to `stream:raw`, and an
update always resets `status` to `pending`.

**Consequences.** Restarting the collector recovers missed messages without
re-queueing the ones it already had — a property with its own test. The parser is
never woken for a message whose text and edit date are identical to what is
already stored.

### 1.5 The daily join budget lives in Postgres

**Context.** SPEC 4.2 caps joins per account per day. Joining is the behaviour
most likely to get a userbot banned.

**Decision.** `tg_accounts.joins_today` and `joins_reset_at`, consumed through
`accounts.claim_join_slot()` under `SELECT ... FOR UPDATE`.

**Consequences.** A restart cannot hand the account a fresh allowance, and two
collector processes cannot both spend the last slot. `COLLECTOR_MAX_JOINS_PER_DAY`
is validated at `le=50` so a typo cannot turn 5 into 500.

### 1.0 SeaweedFS replaces MinIO as the object store

**Context.** The first CI run against a real remote failed at `make up`. MinIO has
withdrawn its community images from every public registry: `minio/minio` returns
404 from Docker Hub's repository API and 401 from the registry, `quay.io/minio/minio`
requires authentication, and `dl.min.io` answers 410 Gone for the server and `mc`
binaries. The only reason the stack still ran here was a 13-month-old local image
cache. A fresh VPS would have failed exactly as CI did.

**Decision.** SeaweedFS 4.51 (`chrislusf/seaweedfs`, digest-pinned), all-in-one
`weed server -s3`, S3 API on port 8333. The product owner chose it over pinning
Bitnami's frozen MinIO archive.

**Consequences.** No application code changed — `core/s3.py` speaks plain S3 through
aioboto3, and all 193 tests pass against SeaweedFS untouched. Three things did:

- The `minio-init` container is gone. Buckets are now created by `uyhub init-storage`,
  our own already-tested code, so local, CI and production run the same path.
- Anonymous read is a static identity in the S3 config rather than a bucket policy
  applied at runtime. **Without an identity file SeaweedFS grants anonymous full
  access**, so the config is written at container start from `S3_SECRET_KEY`; a test
  asserts `uyhub-media` is anonymously readable and `uyhub-raw` is 403.
- `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` are gone; there is one credential pair,
  `S3_ACCESS_KEY`/`S3_SECRET_KEY`, which both configures the server and authenticates
  our client.

One SeaweedFS behaviour bit us and is worth remembering: each bucket becomes its own
collection and each collection needs a volume, with a default of eight 30 GB volumes.
The test suite creates a bucket per test and exhausted them, failing with an opaque
`InternalError` on PutObject. `-master.volumeSizeLimitMB=1024 -volume.max=0` bounds
the volume count by disk instead.

### 1.6 `sources` gets its own CLI sub-command group

**Context.** Phase 0's CLI is a flat list of commands. Source management needs
five verbs.

**Decision.** `app.add_typer(sources_app)`, giving `uyhub sources
add|list|pause|resume|remove`. Each is one short transaction followed by a
`sources:changed` publish on Redis.

**Consequences.** A running collector picks up the change within a second without
a restart, and falls back to a 60-second refresh if the notification is missed.

---

## Phase 2 — Parser

### 2.1 The parser's output lives in `raw_messages.extracted`

**Context.** SPEC section 3 has no table for extracted fields: they only become
columns in Phase 3, when dedup turns them into a listing. Phase 2 therefore had
nowhere to put its result.

**Decision.** A nullable `JSONB` column on `raw_messages`, holding a serialised
`parser.schema.Extraction` (migration `0003`).

**Consequences.** The parser's output is inspectable with a `SELECT`, which is
how its accuracy gets checked against real posts. `uyhub reparse` becomes
meaningful — there is a previous answer to compare against. Phase 3 reads the
column rather than re-extracting, so extraction runs once per message no matter
how many times dedup reconsiders it.

### 2.2 Phone numbers are found by operator code, not by shape

**Context.** Uzbek mobile numbers are nine digits. So are so'm prices:
`90 123 45 67` and `650 000 000` differ only in what they mean. A regex for one
matches the other.

**Decision.** `core/phones.py` accepts a bare nine-digit run only when it starts
with a real mobile operator code, and never when a currency word follows it.
Landline codes are excluded entirely — a Tashkent landline in a listing is rare
and `71` collides with too many prices to be worth the recall.

**Consequences.** Prices stay in the description and out of `phone_hashes`, and
the same decision function drives both finding and stripping, so a price can
never be deleted from the description by mistake. The cost is the occasional
landline we do not record.

### 2.3 Terms are data with a `*` wildcard, and matching is by prefix

**Context.** Both languages inflect. Uzbek agglutinates (`gisht`, `gishtli`,
`gishtdan`); Russian declines through six cases (`кирпичный`, `кирпичном`).
Whole-word matching missed most real posts; prefix matching everywhere turned
`дом` into `домашний`.

**Decision.** A term ending in — or containing — `*` matches any word ending;
a term without one must match a whole word. District aliases match by prefix
unconditionally, because the names are distinctive enough to have nothing to
collide with.

**Consequences.** The keyword lists stay readable data that a person who knows
the language can correct, and the choice between the two behaviours is visible
in the term itself rather than buried in the matcher.

### 2.4 Several properties in one post are detected by the room count

**Context.** SPEC 6.6 drops multi-listing posts and has the LLM detect them.
There is no LLM yet. The first attempt rejected a post with two or more phone
numbers *and* two or more prices.

**Measurement.** That attempt was run against the first 47 real posts on
2026-10-28 and rejected **23 of them — half the batch**. Every one was a single
flat. The Tashkent realtor format is `TEL. x / y` (two contact numbers) and
`Narx: 1400$ _ 1200$ Ga Oberladi` (an asking price and the floor they will
accept). Both signals are normal in a single listing, so the rule was measuring
the wrong thing.

**Decision.** Reject as `multi_listing` when the post states **two different
room counts**, or when it has a numbered list *and* two distinct prices. Phone
count is not used at all.

**Consequences.** Real inventory stopped being thrown away: the same 47 posts
went from 23 parsed to 46. A post describing two flats states two room counts;
one describing a price range does not. The asking price is the one kept —
showing the floor would under-promise and surprise the buyer later.

This is what OPEN_QUESTIONS C7 asked for: the share is measured, not assumed.
The number to watch now is how many genuine multi-listing posts slip through,
which only shows up when someone reads the parsed output.

### 2.5 The golden set is grouped JSONL, and only states what a post says

**Context.** SPEC 6.4 wants 150+ posts each with an expected JSON. A directory
of 150 single-post files is unreadable as a set, and the thing a human needs to
do with these is scan them for whether they still look like real posts.

**Decision.** Seven JSONL files under `backend/tests/fixtures/posts/`, grouped
by kind. An `expected` object may omit any field, and only the keys present are
scored.

**Consequences.** A post that genuinely does not name its district is not
counted against district accuracy, so the score measures extraction rather than
how thoroughly the fixtures were annotated. Two fixtures deliberately state no
`deal_type` because their text names neither a verb nor a price — the parser is
right to leave it null, and the fixture says so.

### 2.7 A post with no verb is read as sale or rent from its price

**Context.** SPEC 6.2 expects `deal_type` from the words. A large share of real
posts contain no verb at all — the realtor format is a labelled list ending in
`Narx: 650$`.

**Measurement.** On the first 47 real posts, keying only on words and on prices
above the sale floor left **44 of 46 listings with no deal type**.

**Decision.** When no verb and no rent period are present, the price decides in
both directions: at or above SPEC 6.3's sale floor it is a sale, below it a
rent. Nobody sells a flat for six hundred dollars and nobody rents one for
sixty thousand.

**Consequences.** 45 of 46 of those posts now read as `rent`, which matches the
channel they came from. A post with no verb *and* no price still yields null,
because then there is genuinely nothing to go on.

### 2.8 A blocking stream read must be shorter than the socket timeout

**Context.** The parser died with `TimeoutError: Timeout reading from
localhost:16379` the first time it ran against a queue that had emptied.

**Decision.** `core/redis.MAX_BLOCK_SECONDS` caps how long a consumer may ask
Redis to block, and the client's socket timeout is set above it.
`streams.read_group` clamps its argument to the cap.

**Consequences.** `XREADGROUP ... BLOCK` holds the socket open with nothing on
it, which the client cannot distinguish from a hung connection — with both set
to five seconds, every idle read tore the connection down. The invariant is now
expressed in one place and asserted by a test, rather than being two constants
in different modules that happened to match.

### 2.6 The CI accuracy gate is 90%, and that number is not SPEC 1.5's

**Context.** SPEC 1.5 asks for ≥90% on five fields. The eval currently reports
100% on all five.

**Decision.** CI gates at 90% field accuracy and 95% rejection precision, and
the thresholds are command-line arguments rather than constants.

**Consequences.** **The 100% is not an accuracy measurement.** The golden set is
synthetic and was written alongside the parser that is scored on it — precisely
the trap OPEN_QUESTIONS C4 warns about. The gate exists to catch a regression,
not to certify quality. The real figure arrives when the userbot is logged in
and real anonymised posts replace the synthetic ones; the thresholds move then,
and again when the LLM extractor lands.

---

## Phase 3 — Dedup, media and lifecycle

### 3.1 `price_usd` is frozen at first sight, not recomputed daily

**Context.** Half of listings quote so'm, and the CBU rate moves every day. A
listing's dollar price could track the rate or be fixed when first read.

**Decision.** Computed once, when the seller's posted price is first seen, and
recomputed only when the seller posts a different number.

**Consequences.** `price_history` contains only real price changes, so a
"price dropped" notification means the seller dropped the price — not that the
so'm moved half a percent overnight. The cost is drift: a so'm listing held for
months carries a slightly stale dollar figure. That is the better failure,
because the alternative floods every watcher with false alarms. Closes
OPEN_QUESTIONS B3.

### 3.2 The perceptual hash is ours, not `imagehash`

**Context.** SPEC 7.3 names `imagehash`. It depends on scipy and PyWavelets —
about 150 MB of container image for one function, built on a VPS.

**Decision.** The same algorithm in forty lines of Pillow and numpy: greyscale,
32x32, DCT-II as a matrix product, the top-left 8x8 block, each bit set by
comparison with the median.

**Consequences.** The properties the library would have guaranteed are asserted
directly instead: identical images hash identically, a copy resized to 400px
and recompressed at JPEG quality 70 differs by **0 bits**, and a different
photograph differs by 14. Swapping `imagehash` back in later is one function.

### 3.3 Without a phone there is no `dedup_key`

**Context.** SPEC 7.1 builds the exact-match key from `phone_hash_sorted[0]`.
Many posts have no phone at all.

**Decision.** The key is `None` when there is no phone, and matching falls
through to rules 3 and 4.

**Consequences.** Two genuinely different three-room flats in Chilonzor at the
same price no longer collapse into one listing. The cost is more duplicates
among phone-less posts, which is the right trade: a missed merge is untidy, a
wrong merge shows a user a price belonging to a different flat. Closes
OPEN_QUESTIONS B1.

### 3.4 The longest description wins a merge

**Context.** SPEC 7.2 says to keep "the most complete text" without defining
completeness.

**Decision.** The longest one.

**Consequences.** Objective and needs no trust ranking between sources. It can
pick a chattier post over a denser one; in exchange nothing has to decide which
group is more reliable. Closes OPEN_QUESTIONS B9.

### 3.5 Assembly is serialised per seller by an advisory lock

**Context.** SPEC specifies idempotency per `raw_message_id`, which does not
protect the merge path: two workers handling two reposts of the same flat both
find no match and both create a listing.

**Decision.** `pg_advisory_xact_lock` keyed on the seller's first phone hash,
held for the assembling transaction. A post with no phone takes no lock — there
is nothing to collide on, and rule 2 already declines to match it.

**Consequences.** Work on different sellers still runs in parallel. This is what
makes a second parser replica safe; the prod compose still runs one until that
has been measured rather than assumed. Closes OPEN_QUESTIONS C5.

### 3.6 `trust_score` is the share of a source's posts that become listings

**Context.** SPEC 3 stores the field and feeds it into `quality_score`, but
nothing ever computed it.

**Decision.** A scheduler job sets it to `listings / messages` for sources with
at least 20 messages, floored at 0.3.

**Consequences.** A property channel scores near 1, a chat group near the floor,
and the difference shows up in the feed ordering. The floor matters because the
score multiplies into quality, which gates channel posting — a source should
never be silenced by one bad week. Closes OPEN_QUESTIONS B4.

### 3.7 The text-similarity threshold is 12 bits, not 6

**Context.** SPEC 7.1 rule 3 suggests a SimHash Hamming distance of 6.

**Measurement.** On real collected posts, a repost of the same flat with the
usual edits — one word changed, a line dropped — sits at **9 bits**, while a
different flat sits at **26**. At 6 the rule would never fire.

**Decision.** Default 12, configurable, with the measurement recorded here.

**Consequences.** The gap between 9 and 26 is wide enough that 12 is not a
close call, and rule 3 additionally requires a shared phone, the same deal type,
the same room count and a price within 5% — the text is the last of five
conditions, not the only one.

### 3.8 An unknown property type is stored as `other`, not assumed to be a flat

**Context.** `listings.property_type` is not nullable and defaulted to
`apartment`. A post that never said what it was silently became a flat: it
would answer a user's "apartment" filter on a guess, and because the column was
never null the merge rule that fills empty fields could never correct it. The
derived title told the truth — "2 xonali obyekt" — while the column next to it
said `apartment`, which is how the problem was found.

**Decision.** Default to `other`, the member that already renders as "obyekt",
and treat it the way `building_type` and `renovation` treat `unknown` — a later
sighting that does name the type fills it in and the title is rebuilt with it.

Separately, the extractor now infers `apartment` from a storey-out-of-a-total
(`1Xona 2/4`): a hovli is never the second of four. On the first 120 real posts
this recovered 10 of the 14 listings that had no type at all; the remaining one
is a daily-rental hostel, which is genuinely not one of our categories.

**Consequences.** A listing we cannot classify is missing from a type filter
rather than wrongly present in it — a null is unfilterable, a wrong value is
visible to the user. The honest count is now 26 flats and 1 unknown out of 27,
where the old default would have reported 27 flats.

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
