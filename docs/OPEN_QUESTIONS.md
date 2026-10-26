# Open questions

Things in `docs/SPEC.md` that are contradictory, ambiguous or risky, each tagged with
the phase that must resolve it. Raised during the Phase 0 spec review (2026-10-26).

Status values: **open**, **resolved** (with the decision recorded in `DECISIONS.md`),
**accepted** (understood and deliberately left as is).

---

## Contradictions

| id | Issue | Resolve by | Status |
|---|---|---|---|
| A1 | `make lint` is defined as "ruff, mypy, eslint, tsc" and must pass in Phase 0, but `miniapp/` does not exist until Phase 5. | Phase 0 | **resolved** — DECISIONS 0.9 |
| A2 | CLAUDE.md puts `make eval-parser` (Phase 2) and `make login-userbot` (Phase 1) under "create in Phase 0". | Phase 0 | **resolved** — DECISIONS 0.9 |
| A3 | `COLLECTOR_MAX_JOINS_PER_DAY=5` on one account against 50–200 sources is 10–40 days to finish joining. SPEC 1.3 expects the full source list in the MVP. | Phase 1 | **open** — needs a product call: slow ramp, more accounts earlier, or a prioritised first 30 sources |
| A4 | `LISTING_TTL_DAYS` is one variable with two defaults (30 sale / 14 rent). | Phase 3 | **resolved** — split into `LISTING_TTL_DAYS_SALE` and `_RENT` in `.env.example` |
| A5 | SPEC 14 requires Prometheus metrics; SPEC 16's production service list has no Prometheus, and `/metrics` is internal-only, so nothing would scrape it. | Phase 7 | **open** |
| A6 | Sentry is a foreign SaaS and exception payloads carry post text and phone numbers, which SPEC 13 requires to stay in Uzbekistan. | Phase 7 | **open** — either keep Sentry off in production or make PII scrubbing mandatory and auditable |
| A7 | Retention purges `raw_messages.text` after 90 days, but `parser reparse --since` needs that text to re-run an improved parser over history. | Phase 2 | **open** — reparse is silently capped at 90 days unless text retention is extended for parsed messages |
| A8 | "No test may call real Telegram" vs Phase 1's DoD requiring a real session against 3 test sources. | Phase 1 | **accepted** — the DoD item is a manual acceptance check, not part of `make test` |

## Ambiguities

| id | Issue | Resolve by | Status |
|---|---|---|---|
| B1 | `dedup_key` uses `phone_hash_sorted[0]`. Posts without a phone are common; with an empty first element, two genuinely different 3-room Chilonzor flats at $65k collapse into one listing. | Phase 3 | **open** — proposal: `dedup_key` is NULL without a phone, falling through to rules 3 and 4 |
| B2 | `quality_score` lists its inputs but no formula or weights, yet it gates channel posting at ≥ 60. | Phase 3 | **open** |
| B3 | Is `price_usd` recomputed for UZS listings when a new CBU rate arrives, or frozen at first sight? Affects search results and price-drop notifications. No bootstrap rate exists before the first scheduler run. | Phase 2 | **open** |
| B4 | `sources.trust_score` is stored and feeds `quality_score`, but nothing ever computes it. | Phase 3 | **open** |
| B5 | "An album is stored as one row whose `tg_message_id` is the first message id" — Telethon does not guarantee ordering within `events.Album`. Also undefined: editing one photo of an album, and an album split across two events by the debounce. | Phase 1 | **open** — proposal: define "first" as `min(message_ids)` |
| B6 | `events.MessageDeleted` sometimes arrives without a chat id (SPEC 4.3 notes it but does not resolve it). Matching on `tg_message_id` alone can mark the wrong source's row deleted. | Phase 1 | **open** — proposal: act only when the chat id is present, otherwise log and count |
| B7 | Groups carry Chirchiq, Zangiota and Qibray properties. Is a non-Tashkent post rejected, or stored with `district = null`? | Phase 2 | **open** |
| B8 | A Mini App session open longer than 24 h has stale `initData`, so every request 401s. | Phase 5 | **open** |
| B9 | Merge keeps "the most complete text" as `description` — longest, or from the most trusted source? | Phase 3 | **open** |
| B10 | `large`/`thumb` must be public while `original` stays private, but SPEC puts all three under one prefix. | Phase 0 | **resolved** — DECISIONS 0.6, two buckets |
| B11 | The parser generates `title_uz` only (SPEC 6.2), so a user on the Russian interface sees Uzbek listing titles next to Russian chrome. Found while running the prototype. | Phase 2 | **open** — options: generate `title_ru` too, compose the title client-side from structured fields, or accept the mix |

## Risks

| id | Risk | Resolve by | Status |
|---|---|---|---|
| C1 | SPEC 13 covers *where* phone numbers are stored but not *whether* harvesting and republishing sellers' numbers, collected without consent from third-party groups, is lawful. The removal flow is opt-out. No phase currently schedules the legal review SPEC 13 refers to. | **before Phase 6** | **open** — the highest-impact open item |
| C2 | `POST /listings/{id}/contact` at 30/user/hour with cheap Telegram accounts makes the whole phone database enumerable. | Phase 4 | **open** |
| C3 | A Telethon userbot violates Telegram's terms; accounts get banned. MVP runs one account, so the pipeline has a single point of failure. Multi-account is "designed for" but never exercised. | Phase 1 | **open** |
| C4 | Phase 2 grades the parser at ≥ 90 % against a golden set the implementer wrote. A model measured on data it authored will score high and prove nothing. | Phase 2 | **open** — real anonymised posts from Phase 1 should be the gate |
| C5 | Production runs 2 parser replicas. Two reposts of the same flat processed concurrently both find no match and both create a listing; idempotency is specified per `raw_message_id`, which does not protect the merge path. | Phase 3 | **open** — proposal: Postgres advisory lock on the phone hash |
| C6 | The LLM's self-reported `confidence` is poorly calibrated but feeds `needs_review` and `quality_score`. | Phase 2 | **open** |
| C7 | Multi-listing posts are dropped entirely (SPEC 6.6). If realtors' multi-property posts are a large share of volume, that silently discards inventory. | Phase 2 | **open** — must be measured, not assumed small |
| C8 | Rotating `PHONE_HASH_KEY` invalidates every `phone_hash` and every `suppressed_phones` row, re-exposing listings people asked to remove. RUNBOOK promises secret rotation. | Phase 4 | **open** — either document "never rotate" or design a dual-key migration |
| C9 | p95 < 200 ms on 200k rows: the single composite index in SPEC 3 does not cover `sort=price_asc` / `price_per_m2` keyset pagination, and `price_per_m2` is a computed sort needing a generated column or expression index. | Phase 4 | **open** |
| C10 | The 60-second end-to-end SLA is violated by design whenever the LLM budget guard pauses consumption. | Phase 2 | **accepted** — the SLA metric should exclude budget-paused windows |
