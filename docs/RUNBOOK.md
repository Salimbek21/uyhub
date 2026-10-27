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

## 4. Deployment

### 4.1 What to buy

**Server.** One VPS in an Uzbek data centre. SPEC section 13 requires personal data —
which phone numbers are — to be stored on infrastructure physically in Uzbekistan, so
a cheaper VPS in Europe is not an option for production.

| Stage | Spec | Why |
|---|---|---|
| Start / staging | 2 vCPU, 4 GB RAM, 50 GB SSD | Enough for the datastores, API and Mini App while there is no collector traffic |
| Production | 4 vCPU, 8 GB RAM, 100 GB SSD | SPEC section 16's target; Postgres is given 2 GB and MinIO grows with photos |

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

# 3. Firewall: SSH and HTTP(S) only. Postgres, Redis and MinIO are never exposed.
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
openssl rand -base64 32    # -> MINIO_ROOT_PASSWORD (also into S3_SECRET_KEY)

nano .env                  # fill in DOMAIN, ACME_EMAIL and the two passwords
```

### 4.3 Deploying

```bash
cd /opt/uyhub
./infra/deploy.sh            # current checkout
./infra/deploy.sh v0.2.0     # a specific tag
```

The script builds the images, starts the datastores, creates the MinIO buckets, runs
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

`/metrics` is deliberately unreachable from the internet (SPEC 9.1); Caddy returns 404
for it. Prometheus scrapes it over the Docker network from Phase 7.

### 4.5 Watch out for

- **Compose drops `env_file` on `run` for a profiled service** unless the profile is
  named explicitly. `deploy.sh` always passes `--profile`; if you invoke `migrate` or
  `minio-init` by hand, do the same or the container starts with no configuration at
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
