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

## 3. `scripts/repopulate.py` can lose cache entries

It deletes every poisoned entry before re-fetching, and `openreview.resolve` in
its refetch loop is unguarded. Run without credentials or with the network down,
it deletes ~29 entries and aborts on the first `AuthError`, restoring none.

The deletion *condition* is narrow and safe — prefix-scoped, and only entries
whose payload is `{}` or whose `title` is `""`. A legitimately-empty result is
only ever re-fetched to the same empty value. So the exposure is a lost cache
entry, recoverable by re-running with credentials, not a wrong one.

**Do:** check credentials before deleting anything, or delete each entry only
once its replacement has been fetched.

## 4. One test is vacuous on inserted lines

`tests/test_emit.py::test_ris_projection_changes_only_py_and_jf_lines` pairs
input and output lines by `zip` index. Since `project_ris` gained the ability to
*insert* a line, any record where an insertion shifts lines makes the comparison
meaningless. Its stated purpose — guarding `_TAG_FOR`'s scope on *substitution*
— still holds, and the comment discloses the limit.

This is the fifth instance in this build of a test whose name claimed a
guarantee it did not check. The other four were fixed.

**Do:** align by tag rather than index, so the guard survives insertions.

## 5. Authors and abstracts are never recovered

Measured: 0 of 2,413 records get either field from a non-Scholar source. Scholar
truncates 71% of author lists and effectively every abstract, and scholarmend
leaves both exactly as it found them.

This is deliberate, and documented in the design document and the README. It
stays unbuilt because it would currently buy nothing: the RIS projection rewrites
only `PY` and `JF`, so recovered authors would sit in the canonical JSON with no
consumer — Covidence and `venuetriage` both read the RIS.

**Closing it properly needs three changes together, not one:**

1. emit the fields — OpenReview's API already returns `authors` and `abstract`
   in a note's `content`, and Semantic Scholar needs a wider field list
2. extend the projection to rewrite `AU` and `AB`
3. accept what that costs the round-trip guarantee: rewriting an author list
   means deleting N lines and inserting M, which is categorically unlike the
   single-line insertion the projection does today

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

## 9. A venueid derived from an invitation cannot carry acceptance status

When `/notes?forum=…&limit=1` returns a Decision note rather than the
submission (25 of 96 real forums), `venueid_from_invitations` derives the venue
from `…/Conference/Submission5047/-/Decision` -> `…/Conference`. Every paper
at that conference has such an invitation, accepted or not, so a rejected paper
with a public forum (ICLR publishes them) would read as main track, published.
The cache stores the venueid *after* derivation, so derived and genuine entries
cannot be told apart from the committed cache alone.

No harm measured: the reviewers found 0 disagreements over the 90 labelled
venueids, and all 166 records venuescout's escalation moves to MAIN are MAIN by
the reviewers' labels. The corpus is accepted papers; the gap is latent.

**Do:** fetch the submission note itself -- in API v2 the forum id is the
submission note's id, so `GET /notes?id={forum}` returns the note that carries
`content.venueid` -- and drop the invitation fallback, or keep it only with a
`derived: true` flag in the cached payload that downstream treats as no
evidence of acceptance. Either way the existing cache needs repopulating
(`scripts/repopulate.py`, credentials required). Verify the `?id=` behaviour
against the live API before building on it; it is from memory, not measured.

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
