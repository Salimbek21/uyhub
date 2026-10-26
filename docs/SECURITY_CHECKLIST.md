# Security checklist

Reviewed and signed off in Phase 8 (SPEC 15). Items are checked off in the phase that
implements them, so the Phase 8 review is a verification pass rather than a scramble.

Legend: ✅ done · ⬜ not yet · ➖ not applicable yet

---

## Secrets

- ✅ All configuration from environment variables via pydantic-settings
- ✅ `.env*` (except the example), `*.session`, backups and keys in `.gitignore`
- ✅ `gitleaks` runs on every commit through pre-commit
- ✅ A pre-commit hook refuses to commit `.env` or `*.session` outright
- ✅ Secrets wrapped in `SecretStr` so they do not appear in `repr()` or tracebacks
- ✅ Connection strings have their password masked before being logged
- ⬜ Production `.env` exists only on the server, mode 0600 — Phase 8
- ⬜ `PHONE_HASH_KEY` and `BACKUP_PASSPHRASE` generated on the server — Phase 8
- ⬜ A documented, tested rotation procedure for every secret — Phase 7/8
      (blocked by `OPEN_QUESTIONS.md` C8: `PHONE_HASH_KEY` has no safe rotation path yet)

## Personal data

- ✅ Logs strip phone numbers from fields, free text and nested structures
- ✅ Logs redact tokens, API keys, session strings and `initData`
- ✅ Post text truncated in logs rather than written in full
- ⬜ Phones in plaintext only in `listings.phones`; HMAC elsewhere — Phase 1
- ⬜ Retention jobs for `raw_messages` (90 d) and old listings (180 d) — Phase 7
- ⬜ Seller self-removal suppresses by phone hash — Phase 6
- ⬜ Production data stores physically in Uzbekistan — Phase 8
- ⬜ Legal basis for storing scraped phone numbers confirmed — **before Phase 6**

## Application

- ✅ `mypy --strict` clean; ruff with bandit (`S`), async (`ASYNC`) and tz (`DTZ`) rules
- ✅ Every external call has a timeout and bounded retries
- ✅ Liveness touches no dependency; readiness reports an exception class name, never a DSN
- ✅ API docs disabled when `APP_ENV=production`
- ⬜ Every API parameter validated by Pydantic — Phase 4
- ⬜ SQL only through SQLAlchemy, no string-built SQL — every phase
- ⬜ `initData` HMAC validated, `auth_date` older than 24 h rejected — Phase 4
- ⬜ Rate limiting per user and per IP — Phase 4
- ⬜ Strict CORS, Mini App origin only — Phase 4
- ⬜ Contact reveal cannot be used to enumerate the phone database — Phase 4
      (`OPEN_QUESTIONS.md` C2)

## Infrastructure

- ✅ Container images pinned by digest
- ✅ Local ports bound to 127.0.0.1 only
- ✅ Dependencies locked (`uv.lock`), `--frozen` enforced in CI
- ✅ `pip-audit` runs on every PR (report-only — see DECISIONS 0.12)
- ⬜ `pip-audit` and `npm audit` block the build — Phase 8
- ⬜ Containers run as non-root with a read-only root filesystem where possible — Phase 8
- ⬜ Only Caddy exposes ports; Postgres, Redis and MinIO on the internal network — Phase 8
- ⬜ Automatic HTTPS for `app.`, `api.` and `media.` — Phase 8
- ⬜ MinIO: `uyhub-media` public read, `uyhub-raw` private, verified in production — Phase 8
- ⬜ Dependabot or equivalent enabled — Phase 8
- ⬜ Encrypted backups with a tested restore — Phase 7

## Telegram

- ✅ `make login-userbot` is documented as human-only; credentials are never logged
- ⬜ The userbot only reads: never sends, reacts or forwards — Phase 1
- ⬜ Joins capped by `COLLECTOR_MAX_JOINS_PER_DAY` — Phase 1
- ⬜ Session file mode 0600 in a volume — Phase 1
- ⬜ Separate bot tokens for staging and production — Phase 6
- ⬜ Admin commands gated on `users.is_admin` — Phase 6
