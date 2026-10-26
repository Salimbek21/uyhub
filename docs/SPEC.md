# UyHub — Product & Technical Specification

Version 1.0. Owner: product team. Implementer: Claude Code, working phase by phase (section 17).

---

## 1. Product

### 1.1 Problem
In Tashkent, real-estate listings are scattered across hundreds of Telegram groups and channels. The same flat is reposted in 10–20 places, posts are unstructured (Uzbek Latin, Uzbek Cyrillic, Russian, mixed), and there is no way to filter by district, price or rooms. Buyers and renters waste hours scrolling.

### 1.2 Solution
One place where every listing appears once, in a clean structured form, searchable with filters, with instant notifications for saved searches.

### 1.3 MVP scope
- City: Tashkent only (12 districts, see 6.5).
- Deal types: sale, rent.
- Property types: apartment, house (hovli), land (uchastka), commercial, room. Apartments and houses are the priority; others are stored but may be lower quality.
- Sources: 50–200 public groups/channels. Expected volume: 5,000–20,000 messages/day, of which roughly 30–50% are real listings.
- Surfaces: Mini App, bot, one auto-posting channel.
- UI languages: Uzbek (Latin) and Russian.

### 1.4 Non-goals for MVP
Map view, other cities, payments/monetization, realtor accounts, posting listings by users directly, mobile native apps, OLX/other site integrations. Design the data model so these can be added later without rewrites.

### 1.5 Success metrics
- p95 latency from post in source to listing visible in API: under 60 seconds.
- Parser field accuracy on the golden set: at least 90% for deal_type, property_type, rooms, price_usd, district.
- Duplicate rate visible to users: under 5% (measured by manual sampling of 100 listings).
- Uptime of API and Mini App: 99.5% monthly.

---

## 2. Architecture

### 2.1 Services (one Python package, several entrypoints, one Docker image)
| Service | Entrypoint | Responsibility |
|---|---|---|
| collector | `uyhub collector` | Telethon userbot(s): join sources, listen to new/edited/deleted messages, backfill gaps, download photos, write `raw_messages`, push to `stream:raw` |
| parser | `uyhub parser` | Consume `stream:raw`: prefilter, regex extraction, LLM extraction, normalization, then dedup/merge into `listings`; push to `stream:listings` |
| api | `uyhub api` | FastAPI for the Mini App, admin endpoints, health, metrics |
| bot | `uyhub bot` | aiogram 3: user commands, saved-search notifications (consume `stream:listings`), admin commands, seller removal flow |
| poster | `uyhub poster` | Consume `stream:listings`, post qualifying new listings to the channel with rate limiting |
| scheduler | `uyhub scheduler` | Periodic jobs: exchange rates, listing expiry, retention cleanup, daily digests, stats |
| miniapp | static build served by Caddy | React SPA |

### 2.2 Data flow
Telegram sources → collector → Postgres `raw_messages` + MinIO photos → Redis Stream `stream:raw` → parser → Postgres `listings` (+ `listing_sources`, `listing_photos`) → Redis Stream `stream:listings` (events: `created`, `updated`, `status_changed`) → bot notifier, channel poster; API reads Postgres.

### 2.3 Queue rules
- Redis Streams with consumer groups; at-least-once delivery. Every consumer is idempotent (keyed by `raw_message_id` or `listing_id` + event version).
- Failed messages are retried up to 5 times with backoff, then moved to `stream:dead` and counted in metrics. An admin CLI command replays the dead-letter stream.
- `MAXLEN ~` trimming on every stream to bound memory.

### 2.4 Repository layout
```
.
├── CLAUDE.md
├── Makefile
├── .env.example
├── docs/            SPEC.md PROGRESS.md DECISIONS.md RUNBOOK.md PRIVACY.md
├── backend/
│   ├── pyproject.toml
│   ├── src/uyhub/
│   │   ├── core/        config, logging, db, redis, s3, metrics, i18n, clock
│   │   ├── models/      SQLAlchemy models
│   │   ├── collector/
│   │   ├── parser/      prefilter, regex, llm, normalize, schema, prompts/
│   │   ├── dedup/
│   │   ├── media/
│   │   ├── api/
│   │   ├── bot/
│   │   ├── poster/
│   │   ├── scheduler/
│   │   └── cli.py       Typer CLI: all entrypoints + admin commands
│   ├── migrations/
│   └── tests/           unit/ integration/ fixtures/posts/ eval/
├── miniapp/
├── infra/           docker-compose.yml, docker-compose.prod.yml, Caddyfile, backup/
└── .github/workflows/
```

---

## 3. Data model (PostgreSQL)

All tables have `created_at`, `updated_at` (timestamptz, UTC). Primary keys are bigint identity unless noted.

**tg_accounts** — userbot accounts. `label`, `phone_masked` (last 4 digits only), `status` (active, flood_wait, banned, disabled), `flood_until`, `joins_today`, `joins_reset_at`.

**sources** — groups/channels we read. `tg_chat_id` (unique, nullable until joined), `username`, `invite_link`, `title`, `kind` (channel, group, supergroup), `city`, `account_id` → tg_accounts, `status` (pending_join, active, paused, error, left), `last_message_id`, `last_message_at`, `joined_at`, `error_text`, counters (`messages_total`, `listings_total`), `trust_score` (float, default 1.0).

**raw_messages** — immutable copy of what we received. `source_id`, `tg_message_id`, `grouped_id`, `posted_at`, `edited_at`, `deleted_at`, `text`, `media` (jsonb: list of photo refs and S3 keys), `raw` (jsonb, trimmed Telethon dict), `status` (pending, rejected_prefilter, rejected_llm, parsed, failed), `parser_version`, `listing_id` (nullable). Unique `(source_id, tg_message_id)`. An album is stored as one row whose `tg_message_id` is the first message id and whose media contains all photos.

**listings** — the canonical, deduplicated listing.
`id` (uuid), `deal_type` (sale, rent), `property_type` (apartment, house, land, commercial, room, other), `rooms` (smallint), `area_m2` (numeric), `land_sotix` (numeric), `floor`, `floors_total`, `building_type` (brick, panel, monolith, other, unknown), `renovation` (euro, good, cosmetic, needs_repair, none, unknown), `price_amount` (numeric), `price_currency` (USD, UZS), `price_usd` (numeric, computed), `price_period` (null for sale; month or day for rent), `negotiable` (bool), `district` (enum of 12, nullable), `landmark` (text), `address_text`, `title` (short generated title, uz), `description` (original text cleaned: phones and links removed), `phones` (text[] E.164), `phone_hashes` (text[] HMAC-SHA256 of phones), `status` (active, sold, expired, removed), `quality_score` (0–100), `confidence` (0–1), `needs_review` (bool), `dedup_key`, `text_simhash` (bigint), `cover_phash` (bigint), `first_seen_at`, `last_seen_at`, `status_changed_at`, `posted_to_channel_at`, `channel_message_id`, `version` (int, bumped on every material change).
Indexes: `(status, deal_type, district, rooms, price_usd)`, `(status, first_seen_at desc)`, GIN on `phone_hashes`, btree on `dedup_key`, trigram index on `title` and `landmark` (pg_trgm) for text search.

**listing_sources** — `listing_id`, `raw_message_id`, `source_id`, `tg_link` (https://t.me/... or null for private), `seen_at`. Unique `(listing_id, raw_message_id)`.

**listing_photos** — `listing_id`, `position`, `s3_key_original`, `s3_key_large` (1280px webp), `s3_key_thumb` (400px webp), `width`, `height`, `phash`, `sha256`. Unique `(listing_id, sha256)`.

**price_history** — `listing_id`, `price_usd`, `price_amount`, `price_currency`, `observed_at`.

**users** — `tg_user_id` (unique), `lang` (uz, ru), `is_admin`, `notifications_enabled`, `last_active_at`.

**favorites** — `(user_id, listing_id)` primary key.

**saved_searches** — `user_id`, `name`, `filters` (jsonb validated by the same Pydantic model as API filters), `mode` (instant, daily), `active`, `last_notified_at`. Max 10 per user.

**notification_log** — `user_id`, `listing_id`, `saved_search_id`, `sent_at`. Unique `(user_id, listing_id)` so a user is never notified twice about one listing.

**suppressed_phones** — `phone_hash` (unique), `reason` (seller_request, admin, spam), `created_at`. Listings whose phones are suppressed are never shown or posted.

**llm_calls** — `raw_message_id`, `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cost_usd`, `latency_ms`, `ok`, `error`.

**exchange_rates** — `date`, `currency`, `rate_uzs`. Unique `(date, currency)`.

**contact_reveals** — `user_id`, `listing_id`, `revealed_at` (audit and abuse detection).

---

## 4. Collector

### 4.1 Accounts and sessions
- Telethon with a dedicated phone number per account (never a personal account). Credentials: `TG_API_ID`, `TG_API_HASH` from my.telegram.org.
- Session stored as a Telethon session file in a Docker volume with 0600 permissions, path from env. A human creates it with `make login-userbot` (interactive script: phone, code, 2FA password typed in the terminal, never logged).
- Design for multiple accounts from day one: each source is assigned to one account; the collector process runs one Telethon client per active account. MVP runs with one account.

### 4.2 Source management
- Sources are added via CLI (`uyhub sources add <@username | https://t.me/... | invite link>`) or bot admin command. New sources go to `pending_join`.
- A join worker processes `pending_join` sources slowly: public chats via `JoinChannelRequest`, private invite links via `ImportChatInviteRequest`; at most `COLLECTOR_MAX_JOINS_PER_DAY` (default 5) per account, with a random delay of 10–40 minutes between joins.
- After a successful join: store `tg_chat_id`, backfill the last `COLLECTOR_BACKFILL_DAYS` (default 7) days, then mark `active`.
- Pausing a source stops processing its messages but keeps membership. Removing a source leaves the chat.

### 4.3 Live ingestion
- Handlers: `events.NewMessage` (skip messages with `grouped_id`), `events.Album` (one handler call per album), `events.MessageEdited`, `events.MessageDeleted`, all filtered to chat ids of active sources (refresh the set on change via Redis pub/sub, no restart needed).
- New message or album: download photos (see 4.5), upsert `raw_messages`, update `sources.last_message_id`, publish `{raw_message_id}` to `stream:raw`. Handler work must be fast; heavy work goes to background tasks with bounded concurrency.
- Edited: update text/edited_at, reset `status` to pending, re-publish to `stream:raw` (parser treats it as an update of the existing listing).
- Deleted: set `deleted_at`; publish a `source_deleted` event so the lifecycle logic (section 8) can react. Note that deletions in some chat types arrive without chat id; resolve via `(chat_id, message_id)` when available and log otherwise.
- Ignore service messages, messages with no text and no photos, and messages from the userbot itself.

### 4.4 Reliability
- On startup and after every reconnect, for each active source fetch messages with `iter_messages(entity, min_id=last_message_id, reverse=True)` to recover gaps. Same code path as backfill.
- `FloodWaitError`: sleep `seconds + random jitter`, mark the account `flood_wait` with `flood_until`, emit a metric. If any single wait exceeds 1 hour, alert.
- `ChannelPrivateError`, `UserBannedInChannelError` and similar: set source `status=error` with `error_text`, alert admins via bot.
- Heartbeat: write `collector:heartbeat:{account_id}` to Redis every 30 s with TTL 90 s; `/readyz` and alerts use it.
- Graceful shutdown on SIGTERM: stop handlers, finish in-flight downloads (max 20 s), disconnect.

### 4.5 Media
- Photos only in MVP; videos and documents are recorded in `media` as metadata without download.
- Download the largest photo size up to 5 MB, max 10 photos per post. Upload original to MinIO under `raw/{source_id}/{tg_message_id}/{n}.jpg`.
- Resizing, webp conversion, sha256 and pHash happen in the parser stage when a listing is created (section 7), not in the collector.

---

## 5. Parser — stage 1: prefilter and regex

### 5.1 Prefilter (cheap, before any LLM call)
Reject if any is true: text shorter than 25 characters and no photos; text is clearly chat (question without numbers, greetings); contains only links; source-specific ad patterns. Accept for LLM if text contains at least one listing signal in any script, for example:
- Uzbek Latin: sotiladi, sotuvda, ijaraga, ijara, xonali, xona, kv, kvartira, hovli, uchastka, sotix, mo'ljal, remont, ta'mir, narxi, kelishiladi, y.e.
- Uzbek Cyrillic: сотилади, ижарага, хонали, ҳовли, участка, сотих, мўлжал, нархи
- Russian: продается, продаю, сдается, сдаю, аренда, комн, кв.м, квартира, участок, сотки, ориентир, цена, у.е., торг
- Patterns: `\d+/\d+/\d+` (rooms/floor/total floors, very common in Tashkent posts), price with $ or "so'm/сум", Uzbek phone numbers.
Keep the keyword lists in data files (`parser/keywords/*.txt`), not in code. Log and count rejections by reason.

### 5.2 Regex extractors (run before LLM; results are passed to the LLM as hints and used to cross-check)
- Phones: normalize to E.164 `+998XXXXXXXXX` (9-digit national number). Handle spaces, dashes, brackets, leading 8 or 998 without plus, and multiple numbers in one post.
- Price candidates: `65 000$`, `65000 у.е.`, `65k`, `65 ming $`, `650 mln so'm`, `1,2 mlrd сум`, `400$/oy`, `5 mln/месяц`, "kelishiladi/договорная" (negotiable).
- Rooms/floor pattern `R/F/T`.
- Area: `75 kv`, `75 m2`, `75 м²`, `75 кв.м`; land `6 sotix`, `6 соток` (1 sotix = 100 m²).

---

## 6. Parser — stage 2: LLM extraction

### 6.1 Call
- Anthropic Messages API via the official Python SDK. Model from `LLM_MODEL` (default: the current Claude Haiku model; check the Anthropic docs for the exact model id at implementation time and record it in DECISIONS.md).
- Structured output through tool use: define one tool `record_listing` whose `input_schema` is generated from the Pydantic model in 6.2, and force it with `tool_choice`. Validate the tool input with Pydantic; on validation failure retry once with the error message appended, then mark `failed`.
- `temperature` 0, small `max_tokens`. Put the long, static system prompt (rules + few-shot examples) first and mark it for prompt caching so repeated calls are cheap.
- Concurrency limit via semaphore (`LLM_MAX_CONCURRENCY`, default 8). Handle 429/529 with backoff.
- Daily budget guard: if `sum(llm_calls.cost_usd)` for today exceeds `LLM_DAILY_BUDGET_USD`, pause consumption, keep messages queued, alert admins.
- Record every call in `llm_calls`.

### 6.2 Output schema (Pydantic)
`is_listing` (bool), `reject_reason` (str|null), `deal_type` (sale|rent|null), `property_type` (apartment|house|land|commercial|room|other|null), `rooms` (int|null), `area_m2` (float|null), `land_sotix` (float|null), `floor` (int|null), `floors_total` (int|null), `building_type`, `renovation`, `price_amount` (float|null), `price_currency` (USD|UZS|null), `price_period` (month|day|null), `negotiable` (bool), `district` (one of the canonical ids in 6.5 or null), `landmark` (str|null), `address_text` (str|null), `title_uz` (str, max 80 chars, e.g. "3 xonali kvartira, Chilonzor, 75 m²"), `phones` (list[str]), `confidence` (0–1).
Rules in the prompt: never invent values; null when unknown; "y.e./у.е./$/dollar" means USD; "so'm/сум" means UZS; resolve "mln"/"mlrd"; for rent, the period defaults to month; district must be mapped to canonical ids using the alias table (6.5), using the landmark only when unambiguous.

### 6.3 Normalization after LLM
- Cross-check against regex results: if phones disagree, trust regex; if price differs by more than 10x, set `needs_review`.
- `price_usd`: for UZS use the latest CBU rate from `exchange_rates`.
- Sanity rules → `needs_review` and lower confidence: apartment area outside 15–500 m², rooms > 12, floor > floors_total, sale price_usd outside 5,000–5,000,000, rent outside 50–20,000 per month.
- `description`: original text with phone numbers, @mentions, links and repeated emoji removed; keep line breaks.
- `quality_score` (0–100) from: has price, has district, has rooms or area, has photos (and how many), confidence, source trust_score.

### 6.4 Golden set and evaluation
- `backend/tests/fixtures/posts/` holds at least 150 realistic posts (Uzbek Latin, Uzbek Cyrillic, Russian, mixed; sale, rent, house, land, non-listings, spam, multi-listing posts) each with an expected JSON. Start with synthetic posts written in the real style; later the team adds real anonymized ones.
- `make eval-parser` runs the full pipeline on the golden set (using recorded LLM responses by default, real API only with an explicit flag) and prints per-field accuracy and a confusion summary. CI runs it in recorded mode and fails if accuracy drops below thresholds in 1.5.
- Bump `PARSER_VERSION` whenever prompt or logic changes; `uyhub parser reparse --since ... --version-below N` re-processes stored raw messages.

### 6.5 Districts (canonical ids and aliases)
bektemir, chilonzor, mirobod, mirzo_ulugbek, olmazor, sergeli, shayxontohur, uchtepa, yakkasaroy, yashnobod, yunusobod, yangihayot.
Maintain `parser/districts.yaml` with aliases in all scripts and common spellings and old/colloquial names (e.g. Chilanzar, Чиланзар, Юнусабад, Yunusabad, Mirzo-Ulugbek, Мирзо-Улугбекский, Шайхантахур, Yakkasaray, Яшнабад, Сергели, Учтепа, Алмазар). Also allow well-known massiv/kvartal names mapping to a district where unambiguous. This file is data, reviewed by humans.

### 6.6 Multi-listing posts
Some posts contain several properties. MVP: if the LLM detects more than one property, mark `rejected_llm` with reason `multi_listing` and count it. Do not try to split in MVP.

---

## 7. Dedup and listing assembly

### 7.1 Matching (in order; first strong match wins)
1. Same `raw_message` edited → update its existing listing.
2. Exact key: `dedup_key = hash(phone_hash_sorted[0], deal_type, property_type, rooms, district, round(price_usd, -3 for sale / -1 for rent))` among active listings seen in the last 60 days.
3. Same phone hash + same deal_type + rooms + |price diff| ≤ 5% + text SimHash Hamming distance ≤ 6.
4. Cover photo pHash Hamming distance ≤ 6 + same deal_type + rooms (catches posts with different phones, e.g. realtors reposting).
Thresholds are config values; tests cover each rule and the negative cases (same realtor phone, different flats → must NOT merge when rooms or price differ).

### 7.2 Merge behavior
- Add a `listing_sources` row; update `last_seen_at`.
- Fill null fields from the new post; never overwrite a non-null field with null.
- Price change → new `price_history` row, update price, bump `version`, emit `updated`.
- Photos: add new unique photos (by sha256, then pHash) up to 15.
- Prefer the most complete text as `description`.

### 7.3 Media processing
On create/merge: for each new photo, compute sha256 and pHash (imagehash), produce `large` 1280px and `thumb` 400px webp, store in MinIO under `listings/{listing_id}/`, strip EXIF. Run in a thread pool.

---

## 8. Listing lifecycle
- `active` on creation if `is_listing` and the phone is not suppressed.
- `sold`: an edit adds "sotildi/sotilgan/продано/продана/сдано/ijaraga berildi", or an admin marks it.
- `expired`: no new sightings for `LISTING_TTL_DAYS` (default 30 for sale, 14 for rent). A repost re-activates it.
- `removed`: seller request, admin, or suppressed phone. Removed listings never come back automatically.
- Source deletion: if all sources of a listing deleted their posts and the listing is older than 3 days, mark `expired`; otherwise keep (people delete and repost).
- Every status change bumps `version` and emits `status_changed`.

---

## 9. API (FastAPI)

### 9.1 Auth
- Mini App sends `Authorization: tma <initData>`. Validate with HMAC-SHA256 per Telegram's Mini App documentation using the bot token; reject if `auth_date` is older than 24 h. Upsert `users` on each request (throttled).
- Admin endpoints require `users.is_admin`.
- No auth for `/healthz`. `/metrics` only on the internal network.

### 9.2 Endpoints (prefix `/v1`)
- `GET /listings` — filters: `deal_type`, `property_type`, `district` (multi), `rooms_min`, `rooms_max`, `price_min`, `price_max` (USD), `area_min`, `area_max`, `has_photos`, `q` (text in title/landmark), `sort` (new, price_asc, price_desc, price_per_m2). Cursor pagination (opaque cursor), page size 20, max 50. Returns cards: id, title, price, price_usd, price per m², district, rooms, area, floor/floors_total, thumb URL, photo count, first_seen_at, is_favorite.
- `GET /listings/{id}` — full detail without phones, plus source links and price history.
- `POST /listings/{id}/contact` — returns phones; logged in `contact_reveals`; rate limit 30 per user per hour.
- `GET /favorites`, `PUT /favorites/{listing_id}`, `DELETE /favorites/{listing_id}`.
- `GET /saved-searches`, `POST /saved-searches`, `PATCH /saved-searches/{id}`, `DELETE /saved-searches/{id}`.
- `GET /meta` — enums, districts with localized names, price ranges for sliders.
- `POST /listings/{id}/report` — wrong data, sold, spam.
- Admin: `GET /admin/stats`, `GET /admin/review` (needs_review queue), `PATCH /admin/listings/{id}`.
- `GET /healthz` (process up), `GET /readyz` (DB, Redis, S3 reachable).

### 9.3 Non-functional
- p95 under 200 ms for `/listings` with 200k listings in the table (seed script provided).
- Rate limiting per user and per IP (Redis token bucket).
- Strict CORS: only the Mini App origin.
- Photos served by Caddy from MinIO via a read-only public path for `large` and `thumb` only, long cache headers; originals are private.

---

## 10. Mini App
- Screens: Feed (cards + quick filter chips: Sotuv/Ijara, rooms, district), Filter sheet (all filters, price slider), Listing detail (photo gallery with swipe, key facts grid, price and price per m², district and landmark, description, "Show phone" button which calls the contact endpoint then offers tap-to-call, "Original post" links, report button, favorite toggle), Favorites, Saved searches (create from current filters, choose instant or daily), Settings (language, notifications), Privacy policy.
- Use Telegram theme params for colors (light/dark), BackButton for navigation, MainButton for primary actions, haptic feedback on favorite.
- Skeleton loaders, empty and error states, infinite scroll, lazy images, works on small screens (360 px wide).
- i18n uz (Latin) default, ru. Number formatting: `65 000 $`, `650 000 000 so'm`.
- Built as static files served by Caddy at `https://app.<domain>`; API at `https://api.<domain>`.

---

## 11. Bot (aiogram 3)
- `/start`: language choice on first run, short intro, button that opens the Mini App.
- Saved-search notifications: consume `stream:listings` `created` events (and `updated` with price drop ≥ 5%), match against active saved searches (filters compiled to a fast in-memory matcher, refreshed every minute), send a compact card with photo, title, price and a Mini App deep link to the listing. Instant mode: max 10 notifications per user per hour, overflow goes to the next digest. Daily mode: one digest at 09:00 Asia/Tashkent.
- Respect Telegram limits: global send rate limiter (default 25 msg/s), handle `RetryAfter`, mark users who blocked the bot as `notifications_enabled=false`.
- `/stop` disables notifications.
- Seller removal flow: "Remove my listing" → user shares contact via request_contact button → if the shared phone (must belong to the sender) matches any listing phone, mark those listings `removed` and add the phone hash to `suppressed_phones`; confirm to the user.
- Admin commands (only `is_admin`): `/addsource <link>`, `/sources`, `/pause <id>`, `/resume <id>`, `/stats` (ingested, listings, LLM cost today, queue lag), `/review` (next needs_review listing with approve/fix/remove buttons). Admins also receive alerts (section 14).

---

## 12. Channel poster
- Posts only `created` listings with `quality_score ≥ POSTER_MIN_QUALITY` (default 60), status active, at least 1 photo, price and district present, not posted before.
- Format: album of up to 4 photos with caption: title, price, rooms/floor/area, district + landmark, 2–3 lines of description, hashtags (`#Chilonzor #3xona #sotuv #kvartira`), and an inline button "Batafsil / Подробнее" deep-linking to the listing in the Mini App. Phones are not shown in the channel by default (`POSTER_SHOW_PHONE=false`); the Mini App reveals them.
- Rate limit: one post every `POSTER_INTERVAL_SECONDS` (default 20), queue the rest; skip listings older than 6 hours in the queue.
- When a posted listing becomes sold/removed, edit the caption to add "SOTILDI / ПРОДАНО" (or remove for `removed`).

---

## 13. Privacy and legal
- Uzbekistan's personal data law requires personal data of citizens to be stored on servers located in Uzbekistan. Production DB, Redis and MinIO must run on infrastructure physically in Uzbekistan. Phones are personal data. The team will confirm details with a lawyer; the system must not block this (no foreign managed DB in prod).
- Store phones only in `listings.phones`; everywhere else use HMAC hashes (`PHONE_HASH_KEY`).
- Retention: `raw_messages.text` and `raw` purged after 90 days (keep ids and status); listings expired/sold for more than 180 days have phones and description cleared.
- Every listing keeps a link to the original post (attribution).
- Privacy policy page (uz/ru) in the Mini App and `docs/PRIVACY.md`.
- Seller removal (section 11) works without contacting support.

---

## 14. Observability and operations
- Prometheus metrics at least: `messages_ingested_total{source}`, `prefilter_rejected_total{reason}`, `llm_calls_total{ok}`, `llm_cost_usd_total`, `parse_failed_total`, `listings_created_total`, `listings_merged_total{rule}`, `pipeline_latency_seconds` (posted_at → listing visible), `stream_lag{stream}`, `notifications_sent_total`, `channel_posts_total`, `collector_flood_wait_seconds_total`, HTTP request metrics.
- Sentry for exceptions in all services and the Mini App (`SENTRY_DSN`, optional).
- Alerts sent to admins via bot (scheduler checks every minute): no messages ingested for 30 min (daytime) / 2 h (night); collector heartbeat missing; stream lag > 5 min; LLM error rate > 5% over 10 min; daily LLM budget at 80% and 100%; disk > 80%; any source in `error`.
- Backups: nightly `pg_dump` (compressed, encrypted with `BACKUP_PASSPHRASE`) to a second storage location in Uzbekistan, 14 daily + 8 weekly retention; MinIO bucket mirrored weekly. A documented and tested restore procedure in RUNBOOK.md.

---

## 15. Security
- All secrets from env; production `.env` exists only on the server, file mode 0600.
- Containers run as non-root, read-only root filesystem where possible, only Caddy exposes ports (80/443). Postgres, Redis, MinIO bound to the internal Docker network.
- Dependency pinning via `uv.lock` and `package-lock.json`; Dependabot or equivalent enabled; `pip-audit` and `npm audit` in CI.
- Input validation on every API parameter via Pydantic; SQL only through SQLAlchemy (no string-built SQL).
- Security checklist reviewed in Phase 8 and stored in `docs/SECURITY_CHECKLIST.md`.

---

## 16. Deployment
- Target: one VPS in an Uzbek data center (start with 4 vCPU / 8 GB RAM / 100 GB SSD), Ubuntu LTS, Docker + Compose plugin.
- `infra/docker-compose.prod.yml`: postgres, redis, minio, collector, parser (2 replicas), api, bot, poster, scheduler, caddy. Healthchecks and restart policies on every service. Resource limits set.
- Caddy: automatic HTTPS for `app.`, `api.` and `media.` subdomains (Mini Apps require HTTPS).
- CI (GitHub Actions): on PR — lint, type-check, tests, parser eval (recorded), Mini App build. On tag — build and push the backend image and Mini App bundle, then deploy over SSH: pull, run migrations, `docker compose up -d`, smoke test `/readyz`, roll back to the previous tag on failure.
- Environments: local (compose), staging (same compose on a smaller VPS or same host with a separate project name and a test bot + test channel), production.

---

## 17. Phases and Definition of Done

Each phase ends with: tests green, `make lint` clean, PROGRESS.md and RUNBOOK.md updated, commit made.

**Phase 0 — Foundation.** Repo layout, uv project, Typer CLI skeleton, settings, structlog, Makefile, `.env.example`, docker-compose with Postgres/Redis/MinIO, Alembic baseline, pytest setup with DB/Redis fixtures, pre-commit, GitHub Actions CI, docs skeletons.
DoD: `make up` brings up healthy infrastructure; `make test` and `make lint` pass locally and in CI.

**Phase 1 — Data model and collector.** All tables from section 3 via migrations; `make login-userbot` script; source management CLI; join worker with daily limits; live handlers (new, album, edited, deleted); gap recovery/backfill; photo download to MinIO; FloodWait and error handling; heartbeat.
DoD: unit tests with a fake Telethon client cover albums, edits, deletions, gap recovery and FloodWait; with a real session (human-run login) and 3 test sources, new posts appear in `raw_messages` within 5 s and in `stream:raw`; restarting the collector recovers missed messages.

**Phase 2 — Parser.** Prefilter with keyword data files, regex extractors, LLM client with tool-use schema, prompt caching, budget guard, normalization, exchange rates job, golden set (≥150 posts), `make eval-parser`, reparse command.
DoD: accuracy thresholds from 1.5 met on the golden set (recorded mode); non-listing rejection precision ≥ 95%; no real API calls in tests; cost per 1,000 messages reported by the eval script.

**Phase 3 — Dedup, media, lifecycle.** Matching rules, merge behavior, price history, photo processing (webp, pHash), lifecycle transitions and expiry job, `stream:listings` events.
DoD: fixture scenarios (same flat in 5 groups, realtor with 3 different flats, price drop repost, edited "sotildi", deleted and reposted) all produce the expected listings and events.

**Phase 4 — API.** All endpoints in section 9, initData auth, rate limiting, cursor pagination, seed script with 200k listings, OpenAPI docs.
DoD: endpoint tests including auth failures; p95 for `/listings` under 200 ms on the seeded DB measured by a simple load script.

**Phase 5 — Mini App.** All screens in section 10, uz/ru, Telegram theme integration, connected to the API.
DoD: works inside Telegram on iOS, Android and Desktop against staging; Lighthouse performance ≥ 80 on mobile; no console errors.

**Phase 6 — Bot and channel poster.** User commands, notifications (instant and digest), seller removal flow, admin commands, channel poster with rate limiting and caption updates.
DoD: tests for matching, throttling, dedup of notifications and the removal flow; end-to-end on staging: post in a test source → listing in Mini App → notification received → channel post published, all within 60 s.

**Phase 7 — Operations.** Metrics, Sentry, alerting via bot, backups with encryption and retention, restore test, retention cleanup jobs.
DoD: every alert in section 14 is triggered at least once in a test; a backup is restored into a fresh database and the API works against it; RUNBOOK.md covers all procedures.

**Phase 8 — Production hardening and launch.** Production compose, Caddy, CI deploy with rollback, security checklist, staging soak test for 48 hours with real sources, launch checklist.
DoD: production deployed via CI from a tag; 48-hour soak on staging without unhandled errors or growing queue lag; security checklist complete; launch checklist signed off by me.

---

## 18. What the human provides (Claude Code must ask for these at the right phase, never earlier)
- Phase 1: `TG_API_ID`, `TG_API_HASH`, a dedicated SIM/phone number for the userbot (login done by the human), list of initial test sources.
- Phase 2: `ANTHROPIC_API_KEY` (only needed for recording fixtures and the real-mode eval), `LLM_DAILY_BUDGET_USD`.
- Phase 6: bot token from @BotFather (separate bots for staging and production), test channel and production channel with the bot as admin, admin Telegram user ids.
- Phase 8: domain and DNS access, VPS in Uzbekistan with SSH access, Sentry DSN (optional), backup storage location, `PHONE_HASH_KEY` and `BACKUP_PASSPHRASE` generated on the server.
