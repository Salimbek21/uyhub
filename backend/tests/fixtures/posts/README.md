# Golden set

One JSON object per line. `make eval-parser` runs the real pipeline over every
line and reports per-field accuracy against `expected` (SPEC 6.4).

```json
{"id": "sale-uz-001", "text": "...", "photos": 3,
 "expected": {"is_listing": true, "deal_type": "sale", "property_type": "apartment",
              "rooms": 3, "price_amount": "65000", "price_currency": "USD",
              "district": "chilonzor"}}
```

`expected` may omit any field; only the keys present are scored, so a post that
genuinely does not state its district is not counted against the district
accuracy. `price_amount` is compared as a decimal, and the harness converts
both sides with one fixed rate so the score does not move when the real one does.

Grouped into files by kind rather than one file per post: 150 single-file
fixtures are unreadable as a set, and the thing a human needs to do with these
is scan them for whether they still look like real posts.

**These are written in the style of real posts, not copied from them.** SPEC 6.4
calls that the starting point and says real anonymised posts replace it. Until
the collector has run against live sources, treat the numbers `make eval-parser`
prints as a regression signal, not as the accuracy figure from SPEC 1.5 — a
parser measured on text written by the person who wrote the parser flatters
itself (OPEN_QUESTIONS C4).
