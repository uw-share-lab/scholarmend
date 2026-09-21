# scholarmend

Recovers true venue, year and track for Google Scholar RIS exports, by mining
the URL Scholar already put in every record. `src/scholarmend/`, Python 3.10+,
zero runtime dependencies.

## The invariant

**A false drop is silent and unrecoverable; a false keep is caught at
screening.**

Every design decision here follows from that asymmetry. A record whose venue
cannot be determined keeps Scholar's value, is marked unresolved, and goes on to
a human. A record is never removed, and a field is never guessed. When two
sources at the same tier disagree, precedence still applies but the record is
flagged `conflict` — it is never silently picked.

This is why `venue_from_title` returns `None` for a conference it does not
recognise instead of mapping it onto a known one, and why an unrecognised track
token in a proceedings URL raises `UnknownTrack` rather than defaulting to main
track. A confident wrong answer is harder to notice than a crash.

## Constraints that are not negotiable

- **No runtime dependencies.** `dependencies = []` on purpose: this gets
  installed in a hurry near a deadline on a machine someone else administers.
  `urllib`, not `requests`.
- **The test suite makes no network call.** `tests/conftest.py` has an autouse
  fixture that turns any real `urlopen` into a failure. It exists because a
  test once hardcoded a cache key that did not match the one production derives,
  fell through to the loader, and hit a live API until it returned 429. That
  guard has since caught production code reaching for the network unasked.
  Never disable it; never add a test that needs it off.
- **Precedence is data, in one table.** `ledger.PRECEDENCE` encodes measurements,
  not opinions: Scholar loses all 1,264 year disagreements in the corpus, and the
  OpenReview `venueid` matched the reviewers' label 90 times out of 90. A source
  *absent* from a field's tuple is excluded from answering it — that is how
  preprint sources supply `authors` but never `venue`. Do not scatter this logic
  into `if` branches.
- **`--offline` hard-fails on a cache miss.** A flag that promises determinism
  and quietly reaches the network invalidates the claim it exists to make.
- **The cache is committed.** `.scholarmend-cache/` is the artifact that backs
  the reproducibility claim: a rerun replays it and makes zero API calls. Each
  entry stores the original key beside the payload so the store is auditable by
  reading it, not only by replaying it.
- **The RIS projection substitutes and inserts; it never restructures.**
  `emit.project_ris` may replace a line or insert a missing one before `ER  - `.
  It must never delete N lines and insert M — which is why `AU` and `AB` are not
  in `_TAG_FOR`. Downstream tools were written against Scholar's exact output,
  including the trailing space on `ER  - ` and the `AU  - ...` truncation marker.
  `tests/test_emit.py` guards this; read it before touching the projection.

## The validation corpus

`../Trust-Evals-LitReview/` is a sibling repository and is **read-only**. It
holds the 2,413-record corpus and the ground truth two researchers produced by
hand on 2026-09-20 — 90 OpenReview venueids, 112 labelled records, 10 merge
pairs, 7 overrides. Every acceptance test skips cleanly when it is absent, so
someone who cloned only this repo can still run the suite.

Those numbers are the project's claims. **If a test asserting one of them fails,
investigate — do not adjust the assertion.** Seven defects in this codebase's
plan were found by people who stopped instead of editing a number to pass.

## What it does not do

It never recovers authors or abstracts: 0 of 2,413 records. See `BACKLOG.md` §5
for why, and what closing that gap would actually take.

## Commands

```bash
pip install -e ".[dev]"

pytest                         # 190 tests, offline, ~0.6s
ruff check src tests
mypy src

scholarmend --input ../Trust-Evals-LitReview/corpus --out out --offline
python scripts/repopulate.py   # re-fetch cache entries poisoned by a past bug
```

Tier 2 needs an OpenReview account in `./.env` (gitignored):
`SCHOLARMEND_OPENREVIEW_USER`, `SCHOLARMEND_OPENREVIEW_PASSWORD`. OpenReview
allows 500 requests/hour; `http._respect_rate_limit` paces against it.
