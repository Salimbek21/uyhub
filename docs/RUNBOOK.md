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
# Set POSTGRES_PASSWORD and S3_SECRET_KEY to local values.
chmod 600 .env

# 3. Dependencies, infrastructure, schema
make install
make up
make migrate

# 4. Verify
make check          # probes Postgres, Redis and object storage from the application
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

UyHub publishes **15432** (Postgres), **16379** (Redis) and **19000** (the S3 API),
all on 127.0.0.1, so it can run alongside other local stacks. SeaweedFS has no web
console; inspect objects with the AWS CLI or `uyhub check`.

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

`make clean-volumes` deletes the Postgres, Redis and SeaweedFS volumes. It asks for
confirmation because the data is unrecoverable. `make clean` only removes tool caches
and touches no data.

---

## 2. Adding a source

```bash
uyhub sources add @toshkent_uylar --priority 1    # curated first batch: 1–30
uyhub sources add https://t.me/+AbCdEf123          # private invite link
uyhub sources list
uyhub sources pause 12        # stop reading it, stay in the chat
uyhub sources resume 12
uyhub sources remove 12       # mark as left; leaving the chat itself is manual
```

In production, prefix with Compose:

```bash
cd /opt/uyhub
docker compose -f infra/docker-compose.prod.yml --env-file .env \
    run --rm api sources list
```

What happens next:

1. The source lands in `pending_join`.
2. The join worker takes the lowest `priority` first, at most
   `COLLECTOR_MAX_JOINS_PER_DAY` (5) per account, with a random 10–40 minute gap.
   **Do not raise that number to go faster** — it is the fastest way to get the
   account banned.
3. After joining it backfills history, then flips to `active`.
4. Every change is published on Redis `sources:changed`, so a running collector
   starts reading a new source within a second. No restart needed.

A source that cannot be joined goes to `error` with the reason in `error_text`
(`ChannelPrivateError` means the invite is dead or we were removed).

**Thirty sources takes about six days.** That is the design, not a fault.

## 3. Logging in or re-logging in the userbot

**A human runs this, never an agent and never CI.** It is interactive: the phone
number, the login code and the 2FA password are typed into the operator's own
terminal. They are never written to a log, a file or a chat. The only artefact is
the Telethon session file, mode 0600, in a Docker volume.

Locally:

```bash
make login-userbot
```

On the server, the session has to be created inside the container so it lands in
the `backend_data` volume the collector reads:

```bash
cd /opt/uyhub
docker compose -f infra/docker-compose.prod.yml --env-file .env \
    run --rm -it --entrypoint python collector scripts/login_userbot.py
```

It asks for the phone number, sends a code, and asks for the code and (if set)
the 2FA password. On success it registers the account in `tg_accounts`, storing
only the last four digits of the number.

Then start the collector:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env up -d collector
docker compose -f infra/docker-compose.prod.yml --env-file .env logs -f collector
```

`./infra/deploy.sh` skips the collector when no session file exists and says so;
once the session is there it starts it on every deploy.

### If the account is banned or the session is lost

1. The collector logs `collector.session_missing` or fails readiness.
2. Get a new SIM, run the login above with a different label:
   `TG_ACCOUNT_LABEL=secondary ... scripts/login_userbot.py`.
3. Reassign sources: `UPDATE sources SET account_id = <new> WHERE account_id = <old>;`
4. The new account starts with a fresh join budget and has to re-join every
   source at five per day. This is the single point of failure in the MVP
   (OPEN_QUESTIONS C3).

### Flood waits

A `FloodWaitError` parks the account: `tg_accounts.status = 'flood_wait'` with
`flood_until`. The collector sleeps it out and clears the flag by itself. A wait
over an hour is logged at ERROR as `collector.flood_wait_long` and is worth
looking at — it usually means something raised the request rate.

### Checking the collector is alive

```sql
SELECT label, status, joins_today, flood_until FROM tg_accounts;
SELECT id, status, priority, last_message_at, messages_total FROM sources ORDER BY priority;
SELECT count(*) FROM raw_messages WHERE created_at > now() - interval '1 hour';
```

```bash
redis-cli EXISTS collector:heartbeat:1   # 1 = collecting, 0 = not
redis-cli XLEN stream:raw                # parser backlog
```

## 3b. Running and tuning the parser

The parser consumes `stream:raw`, writes its reading into
`raw_messages.extracted`, and acks. It needs `PHONE_HASH_KEY` set or it refuses
to start.

```bash
uyhub parser                       # locally
docker compose -f infra/docker-compose.prod.yml --env-file .env logs -f parser
```

### Is it keeping up?

```bash
redis-cli XLEN stream:raw          # queue depth
redis-cli XPENDING stream:raw parser
redis-cli XLEN stream:dead         # messages that failed five times
```

```sql
SELECT status, count(*) FROM raw_messages GROUP BY status;
SELECT extracted->>'reject_reason' AS reason, count(*)
  FROM raw_messages WHERE status LIKE 'rejected%' GROUP BY 1 ORDER BY 2 DESC;
```

A growing `stream:raw` with a healthy parser means the parser is slower than the
collector, which at MVP volume should not happen — check the logs before
raising the replica count, and read OPEN_QUESTIONS C5 first: two parsers race on
the merge path until Phase 3 adds the advisory lock.

### Exchange rates

So'm prices are converted to USD with the Central Bank's daily rate. Without a
rate, `price_usd` is left null and the listing drops out of every price filter —
deliberately, because a wrong number there is worse than a missing one.

```bash
uyhub update-rates                 # idempotent; deploy.sh runs it too
```

```sql
SELECT date, rate_uzs FROM exchange_rates ORDER BY date DESC LIMIT 5;
```

A rate older than 14 days is ignored. If the job has been failing, fix it before
worrying about the listings — they recover on the next parse or reparse.

### Improving extraction

The keyword lists and the district table are data, in
`backend/src/uyhub/parser/data/`. Editing them needs no code change:

- `keywords_*.txt` — what marks a post as a listing. Widening these raises
  recall and lowers rejection precision.
- `stopwords.txt` — what marks a post as *not* a listing whatever else it says.
  A stopword beats every signal, so keep entries specific.
- `districts.yaml` — aliases and landmarks. Matching is by prefix, so
  `Chilonzor` already covers `Chilonzorda`. A wrong landmark silently mislabels
  every listing that mentions it; the bar for adding one is high.

After any edit:

```bash
make eval-parser                   # per-field accuracy and the first mistakes
```

Then bump `PARSER_VERSION` and re-run the improved logic over history:

```bash
uyhub reparse --version-below 2 --limit 5000
```

`reparse` only re-queues; the running worker does the work. Messages whose text
retention has already purged are skipped — they cannot be reparsed
(OPEN_QUESTIONS A7).

**The eval's current 100% is not an accuracy figure.** The golden set is
synthetic and was written alongside the parser. Treat the number as a regression
signal until real anonymised posts replace it (docs/DECISIONS.md 2.6).

## 3c. Listings, duplicates and photos

The parser now also assembles listings. One post either joins a listing that
exists or becomes a new one; its photos become public webp; the result is
announced on `stream:listings`.

### Is it working?

```sql
SELECT status, count(*) FROM listings GROUP BY status;

-- How much deduplication is actually happening. A healthy number here is well
-- above 1.0 once several sources are live; 1.0 means nothing is merging.
SELECT round(count(*)::numeric / nullif(count(DISTINCT listing_id), 0), 2) AS posts_per_listing
  FROM listing_sources;

-- Listings with no photo are the ones that look worst in the feed.
SELECT count(*) FILTER (WHERE p.id IS NULL) AS without_photos, count(*) AS total
  FROM listings l LEFT JOIN listing_photos p ON p.listing_id = l.id;
```

```bash
redis-cli XLEN stream:listings     # events waiting for the bot and poster
```

### Too many duplicates, or wrongly merged listings

The thresholds are environment variables; nothing needs rebuilding.

| Variable | Raise it when | Lower it when |
|---|---|---|
| `DEDUP_SIMHASH_MAX_DISTANCE` | the same flat appears twice with near-identical text | two different flats merged |
| `DEDUP_PHASH_MAX_DISTANCE` | the same photo is not recognised across groups | listings merged that share only a generic photo |
| `DEDUP_PRICE_TOLERANCE_PCT` | a repost at a slightly different price made a second listing | flats at genuinely different prices merged |
| `DEDUP_LOOKBACK_DAYS` | old listings are reposted and duplicate | — |

**Which direction to err.** A missed merge shows the same flat twice, which is
untidy. A wrong merge shows a price that belongs to a different flat, which is
wrong in the user's face. When unsure, tighten.

To see why two posts merged, the rule is in the logs:

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env \
  logs parser | grep dedup.matched
```

After changing a threshold, re-run the affected history:

```bash
uyhub reparse --since 2026-10-01 --limit 5000
```

Reparse is safe to repeat: a message that already produced a listing updates
that listing rather than creating another.

### Removing a listing at the seller's request

Phone numbers are stored only as keyed hashes, so suppression works on the
hash. The bot command for this arrives in Phase 6; until then:

```sql
-- The hash is in listings.phone_hashes for the listing in question.
INSERT INTO suppressed_phones (phone_hash, reason)
SELECT unnest(phone_hashes), 'seller_request' FROM listings WHERE id = '<uuid>';
```

The scheduler enforces it within fifteen minutes, across every listing that
phone appears on — including ones collected before the request. Removal is
terminal: nothing brings the listing back automatically.

### Photos

Originals stay private in `uyhub-raw`. The public `large` (1280px) and `thumb`
(400px) webp live in `uyhub-media` under `listings/{listing_id}/`, with EXIF
stripped — a phone's EXIF routinely carries GPS coordinates.

A photo that fails to process is skipped and logged as
`media.unreadable_image`; the listing is still created. If many fail, check
that `uyhub-raw` still holds the originals — the collector writes them, and
nothing else does.

### The scheduler

```bash
uyhub scheduler        # rates, expiry, suppressions, trust scores
```

Every job runs once at startup, so a restart catches up whatever was missed
rather than waiting out an interval. A job that fails is logged as
`scheduler.job_failed` and the others still run — a cbu.uz outage must not stop
listings from expiring.

## 4. Deployment

### 4.1 What to buy

**Server.** One VPS in an Uzbek data centre. SPEC section 13 requires personal data —
which phone numbers are — to be stored on infrastructure physically in Uzbekistan, so
a cheaper VPS in Europe is not an option for production.

| Stage | Spec | Why |
|---|---|---|
| Start / staging | 2 vCPU, 4 GB RAM, 50 GB SSD | Enough for the datastores, API and Mini App while there is no collector traffic |
| Production | 4 vCPU, 8 GB RAM, 100 GB SSD | SPEC section 16's target; Postgres is given 2 GB and object storage grows with photos |

Ubuntu LTS, a public IPv4 address, and SSH key access. Ask the provider to confirm the
data centre is in Uzbekistan, not merely that the company is.

**Domain.** Any TLD works — Telegram only requires HTTPS. A `.uz` domain is sensible
for an Uzbek product. Register through an accredited local registrar: international
resellers charge roughly 30× more for the same name.

**DNS.** Three A records, all pointing at the VPS IP. Caddy issues certificates on
first start, which only works once these resolve:

```
app.<domain>     A   <vps-ip>
api.<domain>     A   <vps-ip>
media.<domain>   A   <vps-ip>
```

**Bot token.** [@BotFather](https://t.me/BotFather) → `/newbot` → a name and a
username ending in `bot`. The reply contains a `123456:ABC-DEF…` string: that is
`BOT_TOKEN`. The API needs it to verify that a request really came from Telegram,
so it is required from the very first deploy, long before the bot itself exists.

Then, still in BotFather, point the Mini App at the deployment:
`/newapp` → pick the bot → title, description, a 640×360 icon → the URL
`https://app.<domain>`. That is what makes the Mini App openable inside Telegram.

Paste the token straight into the server's `.env`. Do not send it over chat.

**A SIM for the userbot** is separate and already covered in section 3 — the
collector account is not the bot.

### 4.2 First-time server setup

```bash
# As root on a fresh Ubuntu LTS box.

# 1. A non-root user for the application
adduser --disabled-password --gecos "" uyhub
usermod -aG sudo uyhub
mkdir -p /home/uyhub/.ssh && cp ~/.ssh/authorized_keys /home/uyhub/.ssh/
chown -R uyhub:uyhub /home/uyhub/.ssh && chmod 700 /home/uyhub/.ssh

# 2. Docker and the Compose plugin
curl -fsSL https://get.docker.com | sh
usermod -aG docker uyhub

# 3. Firewall: SSH and HTTP(S) only. Postgres, Redis and SeaweedFS are never exposed.
ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable

# 4. Disable password and root SSH login
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl restart ssh
```

Then as `uyhub`:

```bash
sudo mkdir -p /opt/uyhub && sudo chown uyhub:uyhub /opt/uyhub
git clone <repository-url> /opt/uyhub && cd /opt/uyhub

cp .env.prod.example .env
chmod 600 .env

# Generate the secrets ON THE SERVER. They are never created on a laptop, never
# sent over chat, and never committed.
openssl rand -base64 32    # -> POSTGRES_PASSWORD (also into DATABASE_URL)
openssl rand -base64 32    # -> S3_SECRET_KEY
openssl rand -hex 32       # -> PHONE_HASH_KEY  (see the warning below)

nano .env
```

Fill in, and `deploy.sh` refuses to run until each is present:

| Variable | Value |
|---|---|
| `DOMAIN` | your domain, without a host prefix — `uyhub.uz`, not `app.uyhub.uz` |
| `ACME_EMAIL` | where Let's Encrypt sends expiry warnings |
| `POSTGRES_PASSWORD` | generated above, and the same value inside `DATABASE_URL` |
| `S3_SECRET_KEY` | generated above |
| `PHONE_HASH_KEY` | generated above — **generate once and never change it** |
| `TG_API_ID`, `TG_API_HASH` | from my.telegram.org, for the collector |
| `BOT_TOKEN` | from @BotFather |
| `CORS_ALLOW_ORIGINS` | `https://app.<domain>` — exactly this, never `*` |
| `MEDIA_PUBLIC_BASE_URL` | `https://media.<domain>` — note: **no bucket name**, Caddy adds it |
| `API_ALLOW_INSECURE_AUTH` | `false`. Deploy refuses otherwise |

> **`PHONE_HASH_KEY` is not rotatable.** Changing it orphans every
> `suppressed_phones` row, which un-suppresses listings whose owners asked to be
> removed, and breaks deduplication against everything already collected. Generate
> it once, back it up with the rest of your credentials, and leave it alone
> (OPEN_QUESTIONS C8).

### 4.3 Deploying

```bash
cd /opt/uyhub
./infra/deploy.sh            # current checkout
./infra/deploy.sh v0.2.0     # a specific tag
```

The script builds the images, starts the datastores, creates the buckets, runs
migrations, starts the API and Caddy, publishes the Mini App bundle, then smoke-tests
`/readyz`. If the smoke test fails it restores the previous image and restarts. It
never touches volumes, so data survives every path through it, including rollback.

The first run takes a few extra minutes while Let's Encrypt issues certificates:

```bash
docker compose -f infra/docker-compose.prod.yml logs -f caddy
```

### 4.4 Afterwards

```bash
curl https://api.<domain>/healthz     # {"status":"ok",...}
curl https://api.<domain>/readyz      # all three dependencies ok
open https://app.<domain>             # the Mini App
```

Then check the things that are wrong in a way nothing else notices:

```bash
# The feed must refuse an anonymous caller. 200 here means the API is open to
# the internet; deploy.sh asserts this too (DECISIONS 6.2).
curl -s -o /dev/null -w '%{http_code}\n' https://api.<domain>/v1/listings       # 401

# Derived photos are public, originals are not. The second one returning 200
# would mean serving untouched camera files, EXIF and all.
curl -s -o /dev/null -w '%{http_code}\n' https://media.<domain>/listings/<id>/0_thumb.webp  # 200
curl -s -o /dev/null -w '%{http_code}\n' https://media.<domain>/../uyhub-raw/<key>          # not 200

# /metrics is internal only (SPEC 9.1).
curl -s -o /dev/null -w '%{http_code}\n' https://api.<domain>/metrics           # 404

# A backup exists within seconds of the first start, not at the end of day one.
ls -lh infra/backup/
```

Finally open the Mini App **inside Telegram**, not just in a browser: that is
the only place `initData` is non-empty, so it is the only place authentication
is actually exercised end to end. In a plain browser every request will be a
401, and that is correct behaviour, not a fault.

Prometheus scrapes `/metrics` over the Docker network from Phase 7.

### 4.5 Watch out for

- **Compose drops `env_file` on `run` for a profiled service** unless the profile is
  named explicitly. `deploy.sh` always passes `--profile`; if you invoke `migrate` or
  `init-storage` by hand, do the same or the container starts with no configuration at
  all. See `DECISIONS.md` 8.2.
- **`caddy_data` holds the TLS certificates.** Deleting that volume forces re-issuance
  and can hit Let's Encrypt rate limits. `deploy.sh` never removes volumes.
- **`DATABASE_URL` points at `postgres`, not `localhost`** in production: it is a
  Docker network hostname, not the host.

## 4b. Staging the Mini App on Vercel

A stopgap while there is no VPS. Vercel gives the Mini App a public HTTPS URL in
minutes, which is the one thing Telegram insists on — it refuses to load a Mini App
over plain HTTP, so without this it cannot be opened inside Telegram at all.

**Scope, and the line not to cross.** Only the Mini App goes here, and only while it
runs on mock data. The API, the database and anything touching a phone number must
live on infrastructure in Uzbekistan (SPEC section 13). Vercel is not. Today the
front end holds no personal data whatsoever, so nothing is at risk; the moment the
real API is wired up (Phase 4), production moves to the VPS and Vercel is demoted to
previewing front-end changes, or dropped.

### Deploying

Vercel needs an account login, which is done by a human, not by tooling or an agent.

```bash
cd miniapp
npx vercel login     # opens a browser
npx vercel --prod    # first run asks a few questions; accept the defaults
```

`miniapp/vercel.json` already sets the framework, the build command, the SPA
fallback and the headers, so the prompts can be answered with their defaults.

Importing from GitHub works too. In that case set **Root Directory** to `miniapp` in
the project settings, or Vercel will try to build the repository root and fail.

### Opening it inside Telegram

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` (a test bot is fine).
2. `/newapp` → choose the bot → paste the Vercel URL.
3. Open the resulting `t.me/<bot>/<app>` link on a phone.

Only then are the parts that cannot be checked in a desktop browser actually
exercised: the native BackButton, haptics, and Telegram's own light/dark theme.

### Why the headers in vercel.json matter

Telegram Web embeds the Mini App in an iframe from `web.telegram.org`. The
`Content-Security-Policy: frame-ancestors` header allows exactly that, and
`X-Frame-Options` is deliberately **not** set — it would override the CSP in some
browsers and the app would render as a blank frame inside Telegram.

## 4c. Running and configuring the API

```bash
make up                                   # Postgres, Redis, SeaweedFS
make migrate
uv --directory backend run uyhub api      # or: uvicorn uyhub.api.app:app
curl -s 'localhost:8000/v1/listings?limit=3' | jq
```

`/docs` is served in every environment except production.

### The variables that matter

| Variable | What goes wrong if it is wrong |
|---|---|
| `BOT_TOKEN` | Without it every authenticated request is rejected with `server_has_no_bot_token`. The API logs a warning at startup when it is missing. |
| `CORS_ALLOW_ORIGINS` | Exact origins, comma-separated, never `*`. Empty means no browser may call the API — a missing value must not silently open it. The Mini App's own origin is the only one that belongs here. |
| `MEDIA_PUBLIC_BASE_URL` | Where a browser reaches the public bucket. Point it at the *public* path only; the originals bucket stays private. Wrong value means every photo is a broken image. |
| `API_RATE_LIMIT_PER_MINUTE` / `_BURST` | Token bucket, per IP and per user. The limiter fails open — if Redis is down, requests pass and a warning is logged. |
| `API_ALLOW_INSECURE_AUTH` | Development only. Accepts callers with no `initData` as a fixed test user. Startup refuses it when `APP_ENV=production`. |

### Getting a `BOT_TOKEN`

Talk to [@BotFather](https://t.me/BotFather) → `/newbot` → the token is the
`123456:ABC-DEF...` string. Put it in `.env` on the server only; it is a
credential and `.env` is gitignored. To rotate it, `/revoke` in BotFather and
replace the value — every `initData` signed by the old token stops validating
immediately, so expect one wave of 401s as open Mini App sessions refresh.

### Serving photos

Derivatives (`*_large.webp`, `*_thumb.webp`) live in the public bucket and are
served directly with long cache headers. Originals live in `uyhub-raw` and must
return 403 to an anonymous request — worth re-checking after any storage
change:

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$MEDIA_PUBLIC_BASE_URL/listings/<id>/0_thumb.webp"   # 200
curl -s -o /dev/null -w '%{http_code}\n' "$S3_ENDPOINT_URL/uyhub-raw/<key>"                     # 403
```

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

### What runs

The `backup` service dumps Postgres into `infra/backup/` once every
`BACKUP_INTERVAL_SECONDS` (default daily), keeping `BACKUP_KEEP_DAYS` (default
14). It runs one dump immediately on start, so a fresh deploy is covered within
seconds. Files are named `uyhub-<UTC timestamp>.sql.gz`.

Photos are **not** backed up (DECISIONS 6.1). A lost photo is a missing image
on a card; a lost `raw_messages` row cannot be recovered at all, because
Telegram history is only retrievable while the post is still up — and the posts
that matter are the ones that get deleted.

```bash
docker compose -f infra/docker-compose.prod.yml logs backup | tail -5
ls -lh infra/backup/
```

Two log events are worth alerting on: `backup_failed`, and
`backup_suspiciously_small`, which fires when a dump is less than half the size
of the previous one — an empty database or a truncated pipe looks like a
successful backup otherwise.

### Restoring

Verified on 2026-10-31 against the development database: 27 listings, 105
attributions, 229 photos and 120 raw messages all came back identical.

Restore into a **throwaway database first** and compare the counts. Never
replay a dump straight over production unless you have already confirmed what
is in it.

```bash
cd /opt/uyhub
DUMP=infra/backup/uyhub-20261031T131230Z.sql.gz        # pick one

# 1. A scratch database alongside the live one.
docker compose -f infra/docker-compose.prod.yml exec postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE restore_check;"

# 2. Replay into it.
gunzip -c "$DUMP" | docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d restore_check -q

# 3. Compare against what you expect to have lost.
docker compose -f infra/docker-compose.prod.yml exec postgres psql -U "$POSTGRES_USER" \
    -d restore_check -c "SELECT count(*) FROM listings;"

# 4. Only then, over the real database — stop the writers first.
docker compose -f infra/docker-compose.prod.yml stop api collector parser scheduler
gunzip -c "$DUMP" | docker compose -f infra/docker-compose.prod.yml exec -T postgres \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -q
docker compose -f infra/docker-compose.prod.yml start api collector parser scheduler

# 5. Clean up.
docker compose -f infra/docker-compose.prod.yml exec postgres \
    psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE restore_check;"
```

The dump is taken with `--clean --if-exists`, so step 4 replaces the schema and
data in place; the database does not need to be dropped first.

### Reclaiming disk

Disk, not memory, is what a small server runs out of. Measured on real data,
originals were 84% of stored bytes and three quarters of them belonged to no
listing at all.

The scheduler's `media_prune` job runs every 6 hours and deletes originals
older than `MEDIA_ORIGINAL_RETENTION_DAYS` (default 7) in two passes: those a
listing has finished with, and those no listing ever claimed. Derivatives — the
only photos ever served — are never touched.

```bash
docker compose -f infra/docker-compose.prod.yml logs scheduler | grep -E 'pruned|prune_skipped'
```

`media.prune_skipped_unprocessed` means originals were found with no derivative
written. They are never deleted — the original is then the only copy of the
photo — but a count that keeps growing means the conversion pipeline is failing
and should be investigated.

If disk still grows faster than expected, check the split before changing the
retention window:

```bash
docker compose -f infra/docker-compose.prod.yml exec seaweedfs du -sh /data
```

Shortening the window reclaims more but leaves less room to rerun a broken
conversion. The better fix at scale is for the collector not to download a
photo it has already seen — see DECISIONS 6.3.

### Still missing

The dumps live on the same machine as the database. A disk failure or a lost
server takes both. Copying `infra/backup/` to a second machine in Uzbekistan
(SPEC 13 requires the data stay in the country) is the next thing to add; until
then these backups protect against a dropped volume, a bad migration and a
mistaken `DELETE`, but not against losing the server.

Rehearse a restore before launch, and again after the first month of real
traffic.

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
