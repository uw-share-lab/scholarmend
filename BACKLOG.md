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

## 8. A rejected submission's venueid is reported as proceedings

Verified 2026-09-21 by calling the function:

    parse_venueid("ICLR.cc/2025/Conference/Rejected_Submission")
    -> venue = ICLR, year = 2025, track = Conference/Rejected_Submission,
       version = proceedings

OpenReview files rejected, withdrawn and desk-rejected papers under the
conference's own venueid, and Scholar indexes their forum pages. The `track`
value exposes it to a careful reader, but `version = proceedings` is simply
false, and `venue = ICLR` reads as a publication to anyone who does not check
the track. None of the 238 cached answers is such a case, so the corpus has not
hit it yet — which is why it went unnoticed, not evidence it cannot happen.

venuescout already guards against it (its `MAIN_TRACKS` allowlist makes such a
record UNKNOWN; see its BACKLOG §3). **Do:** in `parse_venueid`, emit no
`version = proceedings` for a `*_Submission` track that is not plain
`Submission`, and consider leaving `venue` unset for it, so that the invariant
("a field is never guessed") holds here too. A companion change worth making at
the same time: give PMLR claims a structured `title` rather than only
`evidence`, which venuescout currently pattern-matches (its BACKLOG §8).

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
