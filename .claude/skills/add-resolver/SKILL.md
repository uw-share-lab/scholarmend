---
name: add-resolver
description: Add a network resolver to src/scholarmend/resolvers/ — cache keys, tier and confidence, precedence wiring, offline tests, and the live check that catches silent failure. Use when adding a tier-2 or tier-3 source.
---

# Adding a resolver

A resolver turns a key into claims by asking a remote service. It is the only
part of this package that can fail silently, so it gets the most scrutiny.

## Split the parsing from the fetching

Put the logic that turns a response into claims in a **pure module-level
function** — `parse_venueid`, `venueid_from_invitations`, `venue_from_title`.
That is what makes the interesting behaviour testable with no network, no cache
and no credentials, and it is how all 90 gold venueids can be replayed in
milliseconds.

## Cache keys

Derive the key in exactly one place and let tests call that same helper. Never
hardcode a key literal in a test: one did, missed the cache, fell through to the
loader, and hit a live API until it returned 429. Three of its four keys were
wrong and the fourth passed by coincidence.

Every response goes through `Cache.fetch`, which refuses to call a loader under
`--offline`.

## Tier and confidence

Tier 2 is identifier-keyed and trustworthy — confidence ~0.9–0.99. Tier 3 is a
fuzzy title match and is marked down (0.75) and flagged. Add your `source`
string to `ledger.PRECEDENCE` for every field you emit, in the position the
evidence justifies, and say in a comment what measurement justifies it.

Low recall with high precision is the right shape for a last resort. **A
resolver that accepts the wrong paper is worse than one that finds nothing**,
because it launders a wrong venue into the record wearing an authoritative
source label. OpenAlex was rejected for exactly this: it matched 63% of titles
and described the arXiv preprint in every case where it named a venue.

## Test offline, then verify live — and the live step is not optional

Unit tests pre-populate a `Cache`. But the two worst defects in this package's
history were invisible to every offline test, because those tests fed
hand-picked strings to a pure parser and never asked what the API actually
returns:

- `?forum=X&limit=1` returns an **arbitrary** note; 25 of 96 real ids came back
  as a Decision note with no `venueid` at all
- PMLR volume pages use `<h2>`, not `<h1>`, so every lookup returned empty

Both failed silently — the resolver returned `[]` and the record stayed
unresolved. Before you believe a resolver works, run it against the real service
for a sample, count how many come back empty, and explain any that do.
