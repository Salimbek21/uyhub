# Privacy

Skeleton. The user-facing policy text (Uzbek Latin and Russian) is written in Phase 5
alongside the Mini App screen that shows it; the controls it describes are built across
Phases 1–7.

---

## 1. What data the system holds

| Data | Source | Why | Where |
|---|---|---|---|
| Listing text and photos | Public Telegram groups and channels | To show the listing | `raw_messages`, `listings`, object storage |
| Seller phone numbers | Inside those public posts | So a buyer can contact the seller | `listings.phones` (plaintext, required for contact reveal) and `listings.phone_hashes` (HMAC) |
| Telegram user id, language, settings | The user's own use of the bot and Mini App | Favourites, saved searches, notifications | `users`, `favorites`, `saved_searches` |
| Contact reveals | Button presses in the Mini App | Audit and abuse detection | `contact_reveals` |

Phone numbers are personal data under Uzbek law. Everything in this document exists
because of that.

## 2. Rules the implementation must follow

These are derived from SPEC 13 and are enforced in code, not by convention:

1. **Storage location.** Production Postgres, Redis and SeaweedFS run on infrastructure
   physically in Uzbekistan. No foreign managed database in production.
2. **Minimal plaintext.** Phone numbers exist in plaintext only in `listings.phones`.
   Every other reference is an HMAC-SHA256 hash keyed by `PHONE_HASH_KEY`.
3. **Never logged.** `core/logging.py` strips phone numbers from every log event,
   including from free text and from third-party library logs. Implemented in Phase 0.
4. **Retention.** `raw_messages.text` and `raw` are purged after 90 days. Listings
   expired or sold for more than 180 days have phones and description cleared.
5. **Attribution.** Every listing keeps a link to the original post.
6. **Self-service removal.** A seller removes their listings through the bot by sharing
   their own contact; the phone hash goes to `suppressed_phones` and those listings are
   never shown or posted again. No support ticket required.

## 3. Open legal questions

Tracked in `OPEN_QUESTIONS.md`:

- **C1** — SPEC 13 covers *where* phone numbers are stored, not *whether* collecting and
  republishing sellers' numbers from third-party groups without their consent is lawful.
  The removal flow is opt-out. SPEC 13 defers this to a lawyer; no phase currently
  schedules that review. It should be answered before Phase 6 ships contact reveal.
- **A6** — Sentry is a foreign service and exception payloads can carry post text and
  phone numbers, which conflicts with the storage-location requirement.
- **C2** — the contact endpoint's rate limit still allows bulk extraction of the phone
  database across many cheap Telegram accounts.
- **C8** — `PHONE_HASH_KEY` cannot be rotated without invalidating every suppression
  record, which would re-expose listings people asked to remove.

## 4. Policy text

TBD — Phase 5. Must be reachable from the Mini App's Settings screen in both `uz` and
`ru`, and must state: what is collected, why, how long it is kept, that the data comes
from public posts, how a seller removes their listing, and who to contact.
