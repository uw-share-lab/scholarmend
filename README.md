# scholarmend

Recover true bibliographic metadata for Google Scholar exports, so that
screening tools reason over facts rather than over Scholar's truncations.

## Usage

    pip install scholarmend
    scholarmend --input path/to/scholar-exports --out out

`--input` takes a directory of RIS files exported from Google Scholar, or a
single `.ris`. For development, clone the repo and `pip install -e ".[dev]"`.

Tier 1 needs no configuration and resolves venue, year and track for 77% of a
Scholar corpus. Tier 2 needs an OpenReview account:

    export SCHOLARMEND_OPENREVIEW_USER='you@example.edu'
    export SCHOLARMEND_OPENREVIEW_PASSWORD='...'

Every response is written to `--cache` (default `.scholarmend-cache`). Commit
it: a rerun then reproduces byte-identically and makes no API calls.

    scholarmend --input ../Trust-Evals-LitReview/corpus --out out --offline

`--offline` never reaches the network. A record whose lookup is missing from
the cache falls back to tier 1, and the run exits 1 to say it was partial.

### Outputs

| File | Contents |
|------|----------|
| `resolved.json` | canonical records: winning value per field, plus every claim behind it |
| `mended.ris` | the RIS projection, for Covidence and venuetriage |
| `report.txt` | what stayed unresolved, and why |

## The problem

Google Scholar's `.ris` export is the standard input to a systematic review, and
it is lossy in ways that stay invisible until they corrupt a result. Measured on
a 2,413-record corpus of NeurIPS, ICLR and ICML search results:

| Defect | Rate |
|--------|------|
| Venue string ellipsized (`… Neural Information …`) | 98% |
| Author list truncated to five plus `...` | 71% |
| Records carrying a DOI | 2 of 2,413 |
| Scholar's `PY` disagrees with the year in the record's own URL | 68% |

One record shows the whole problem, and its own answer:

    JF  - … Neural Information …
    AU  - ...
    PY  - 2026///
    UR  - https://proceedings.neurips.cc/paper_files/paper/2025/hash/4da4f3c0…-Abstract-Datasets_and_Benchmarks_Track.html

Scholar reports an ellipsis for the venue, the wrong year, and no track. The URL
in the same record states NeurIPS, 2025, Datasets and Benchmarks Track.

## The approach

The identifier in this corpus is not a DOI — there are two — it is the **URL
path**. Offline URL mining yields a key for **99%** of records and fully resolves
venue, year and track for **77%**, with no network access at all. Records are
then escalated per field through cached, credentialed lookups only where mining
leaves a gap.

Every claim is retained with its source, tier, confidence and evidence, so the
losing values stay auditable rather than being overwritten silently.

**Abstracts, on request.** Scholar's `AB` is a search snippet on every record —
fragments joined by `…` around the query terms — and that is what a screening
tool shows reviewers. `--abstracts` replaces it with the paper's abstract, from
the proceedings page, the OpenReview submission note, or Semantic Scholar, in
that order, admitting each only when the source names the record's own title.
Run it on the deduplicated, triaged upload rather than the whole corpus:

    scholarmend --input ../Trust-Evals-LitReview/out/clean.ris --out out-covidence --abstracts

`report.txt` lists every record whose abstract is still Scholar's snippet.

**What it does not recover: authors.** Scholar truncates 71% of author lists,
and scholarmend leaves them as it found them: rewriting `AU` would restructure a
repeated field, which the projection never does. See `BACKLOG.md` §5.

Querying a structured database instead does not work here, and the spec records
the measurement: on a 30-title sample, OpenAlex matched 63% of titles and
returned a correct conference venue for **none** of them, describing the arXiv
preprint instead. The preprint carries a DOI and the proceedings version does
not, so a DOI-anchored index indexes the preprint.

## Validation

scholarmend is tested against hand-verified ground truth rather than against
its own output. The Trust-Evals-LitReview review produced labels for 112
records that escaped an automated rule table and were resolved individually,
with the evidence for each recorded.

| Check | Bar |
|-------|-----|
| Records with an automated resolution path, of those 112 | at least 103 (measured: 104) |
| …of which, venue determined **and verified against the reviewers' labels** | **103**, zero disagreements |
| …the remaining 1 | a sibling proceedings URL, reached but not separately asserted |
| Workshop status against reviewer labels (the 90 OpenReview records) | zero per-record disagreements |
| PMLR volumes against the reviewers' `venue_true` | 10, all out of scope, all correctly declined |
| PMC bridge against the reviewers' override decisions | 3, v267 named ICML 2025, v287 and v297 declined |
| Verdict flips in `decisions.csv` without a recorded reason | 112 flips, **0** unreasoned |
| Per-record overrides | 5 of 10 reproduced; the other 5 asserted unreachable |
| Scholar's year losing every disagreement | all 1,264 |
| Proceedings mining coverage | exactly 1,854 of 2,413 |
| Records with no miner at all | exactly 17 |
| Hand-maintained merge list | retired; 4 collapse at tier 1, 6 at tier 2 |

### What "settled" does and does not mean

The 104 figure counts records for which the miners extract something a live
resolver consumes — a venue directly, or an OpenReview forum id, a PMLR volume
or a PMC id. That is a claim about *reach*, not about correctness, and the two
halves of it are verified to different depths:

- **90 records** reached through an OpenReview `venueid`: venue, year and a
  workshop verdict, every one agreeing with the reviewers' hand-verified label.
  Zero disagreements, compared record by record.
- **10 PMLR volumes**, all out of scope for this review — the Canadian
  Conference on AI, a workshop at ACML, an AAAI bridge programme, a parsimony
  conference. The resolver retrieves each proceedings title and **deliberately
  declines to name a venue**, rather than coerce an unfamiliar conference onto a
  known one. Verified against the volume the reviewers recorded in `venue_true`.
- **3 records via the PMC bridge**, reproducing the reviewers' override
  decisions exactly: PMC volume 267 → PMLR v267 → ICML 2025, named; v287 (CHIL)
  and v297 (ML4H) retrieved and declined.
- **1 record** reached by a sibling proceedings URL, not separately asserted.
- **8 records** have no automated route at all: NSF landing pages, Google Books
  chapters, an SPIE paper, a PDF on a personal page. These needed human
  judgement before and still do — and the suite asserts they resolve to nothing,
  so the day a miner starts covering one, a test says so.

So the honest summary is that scholarmend **determines and verifies** the venue
for **103** of the 112, reaches 1 more without a separate assertion, and leaves
8 untouched.

Run them with the review repository checked out alongside this one:

    pytest tests/test_acceptance.py -v

They skip cleanly when it is not.

## Relationship to other tools

- [`venuetriage`](../Trust-Evals-LitReview) — consumes scholarmend's output to
  separate workshop from main-track papers before Covidence.
- [`refaudit`](https://github.com/uw-share-lab/refaudit) — verifies a finished
  bibliography against Crossref, OpenAlex and arXiv. Different job, different
  input; its DOI-centric resolvers reach only ~8% coverage on this corpus.

## Licence

MIT.
