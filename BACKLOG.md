# Backlog

Everything known to be open, with the measurement behind it. Written when the
implementation merged on 2026-09-20, from the review ledger of that build.

Each item says what was actually checked, so a later reader can tell the
difference between "verified and deliberately deferred" and "never looked at".
Nothing here is a known-wrong behaviour; they are gaps in coverage, evidence
that lives outside the test suite, and one deliberate scope decision.

---

## 1. ~~The suite asserts less than has been verified~~ — CLOSED 2026-09-20

`tests/test_acceptance.py` now asserts all 103 verified records, not 90. Four
tests added: PMLR volumes against the reviewers' `venue_true`, the PMC bridge
against their override decisions, `decisions.csv` verdict-flip reasons, and the
ten per-record overrides split into 5 reproduced and 5 asserted unreachable.
Each was falsified before committing — sabotage the guard, the bridge or a
miner and the corresponding test fails with a real assertion error.

This also closed §2 below.

## 2. ~~Two validation suites the spec names have no test~~ — CLOSED 2026-09-20

The design document lists four validation suites. Two are implemented.

- **`out/decisions.csv`** — "no verdict may flip without an explicit recorded
  reason". Run manually during the final review: **0 flips**, both tier-1-only
  and with gold tier-2 data. No committed test.
- **`overrides-2026-09-20.csv`** — 7 per-record rulings. Referenced by no test
  at all.

**Do:** commit both as tests rather than leaving them to ad-hoc scripts.

## 3. ~~`scripts/repopulate.py` can lose cache entries~~ — CLOSED 2026-09-21

Each entry is now set aside rather than deleted, and put back in a `finally`
unless a replacement was actually written -- on AuthError, HttpError, network
failure and Ctrl-C alike. One failure no longer stops the rest; without
credentials the OpenReview entries are not touched at all. `tests/test_repopulate.py`
(the old script fails all 8); a dry run on a copy of the committed cache
without credentials leaves it byte-identical.

## 4. ~~One test is vacuous on inserted lines~~ — CLOSED 2026-09-21

Worse than recorded. `test_ris_projection_changes_only_py_and_jf_lines` could
not fail on the change it exists to catch: with `"authors": "AU"` added to
`_TAG_FOR` it still passed, because no fixture record carries a non-Scholar
authors claim, and no fixture record triggers an insertion either. It now
aligns lines by diff rather than by `zip`, rejects deletions and restructuring,
adds a tier-2 case carrying year, authors and abstract claims, and asserts that
both the substitution and insertion paths ran. With `AU` added it fails; before,
it did not.

## 5. Authors are never recovered — abstracts CLOSED 2026-09-21

**Abstracts: closed.** Screening in Covidence turned out to be the consumer this
section said was missing: reviewers were reading Scholar's `…`-joined snippets,
with the query term highlighted, in place of every abstract. `--abstracts` now
recovers them from the proceedings page, the OpenReview submission note, then
Semantic Scholar, each admitted only when the source shows the record's own
title. The third objection below did not apply to `AB`: every corpus record has
exactly one `AB` line, and every claim is collapsed to one line, so it is a
one-line substitution like `PY`. Opt-in, because it costs a fetch per record
and the venue work needs none of them.

**Authors: still open**, for the reasons below. Scholar truncates 71% of author
lists and scholarmend leaves them exactly as it found them.

Closing it properly needs three changes together, not one:

1. emit the field — OpenReview's API already returns `authors` in a note's
   `content`, and Semantic Scholar needs a wider field list
2. extend the projection to rewrite `AU`
3. accept what that costs the round-trip guarantee: rewriting an author list
   means deleting N lines and inserting M, which is categorically unlike the
   single-line substitution the projection does today

Doing one third of it adds code and delivers nothing.

## 6. Unexercised configuration

- `PRECEDENCE` lists `openalex` for `authors` and `abstract`; no OpenAlex
  resolver exists. Kept deliberately so the policy exists the day one is added.
  OpenAlex was measured and rejected for venue and year — on a 30-title sample
  it matched 63% of titles and returned a correct conference venue for none of
  them, describing the arXiv preprint instead.
- `miners/proceedings.py` maps `papers.nips.cc`, and `miners/pmlr.py` maps a
  bare `mlr.press`. Both are forward-looking: **0 occurrences** in the corpus,
  and neither has a test.
- DBLP was unreachable from the development machine when measured and remains
  **unmeasured**. It indexes ML proceedings directly rather than via DOI, so it
  is the most promising unexplored tier-3 source. Worth retrying from another
  network.

## 7. Cosmetic and low-risk

Each was reviewed, measured where measurable, and judged not worth blocking on.

| Item | Measurement |
|------|-------------|
| `Ledger.add()` deduplication has no end-to-end test | Relies on `Claim.__eq__`; if that regressed the symptom is duplicate entries in the JSON `claims` array — `resolve()` still returns the same winner |
| `parse._FIELD` does not stitch wrapped continuation lines | 0 of 2,413 `AB` fields wrap, and `AB` is the only such field any code reads |
| `Ledger.resolve()` is O(precedence × claims) | Negligible at this scale; a dict keyed by source would be faster |
| `RESOLVED_FIELDS` is wider than what `unsettled()` escalates | Matches the design; no resolver supplies the extra fields anyway |
| `project_ris` rewrites a line whose value already matches | Unobserved — `PY` is always `NNNN///` and the rewrite reproduces that shape |
| `cli.py` gates `openreview` on credentials but builds the others unconditionally | Safe: `Cache.fetch` refuses to call a loader under `--offline`, and Semantic Scholar needs no key |
| Acceptance asserts `settled >= 103`, a floor | Correct as a regression floor; the measured 104 is not pinned by CI |

---

## 8. ~~A rejected submission's venueid is reported as proceedings~~ — CLOSED 2026-09-21

`parse_venueid` keeps the track verbatim and emits no `version = proceedings`
for any track ending in `Submission`. It had also been stripping a trailing
`/Submission` as "routing detail", but in OpenReview's API v2 that suffix marks
a paper under review or never accepted -- accepted papers get the bare venue --
so an unaccepted submission read as `track = Conference`, published. Venue and
year are still claimed: they say where and when it was submitted. No corpus
number moved; the one cached `*Submission` venueid is a workshop's.

## 9. ~~A venueid derived from an invitation cannot carry acceptance status~~ — CLOSED 2026-09-21

Verified live before building: for rejected ICLR 2025 paper `zkNCWtw2fd`,
`?forum=…&limit=1` returned its Decision note and the old code derived
`ICLR.cc/2025/Conference`, `version = proceedings`. `GET /notes?id={forum}`
returns the submission note with `content.venueid` directly.

The loader now asks for the note by id, trusts only a note whose id is the
forum's and that states its own venueid, and derives nothing; the invitation
fallback is gone. Entries moved to a new key, `openreview:note:` (via
`openreview_key`), so derived and direct values can never mix; all 238 forums
were refetched and the 238 old entries removed (git history keeps them).

236 of 238 came back identical -- every derived entry had been an accepted
paper, so no corpus output was ever wrong. The 2 that changed were empty
before and now state `nesyconf.org/NeSy/2025/Conference[_Phase_2]`
(`psXDX4Q8E5`, `yCwcRijfXz`): the two neuro-symbolic records the R5 audit left
unresolved, now settled as a venue outside the review.

## Provenance

The build ran as thirteen planned tasks with a review after each, then a
whole-branch review, then two fix waves. Twenty-two recorded rulings resolved
conflicts as they arose; seven were corrections to the implementation plan
itself, found by implementers who stopped when the document disagreed with what
they observed rather than editing an assertion to pass.

Two defects were found only by running tier 2 against the live APIs for the
first time — OpenReview returning arbitrary notes without a `venueid`, and PMLR
volume pages using `<h2>` where the code expected `<h1>`. Both were silent: the
resolver returned nothing and the record simply stayed unresolved. No test could
have caught either, because every test fed hand-picked strings to a pure parser.
That is the lesson most worth carrying forward.
