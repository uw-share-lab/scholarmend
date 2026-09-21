# scholarmend

Recover true bibliographic metadata for Google Scholar exports, so that
screening tools reason over facts rather than over Scholar's truncations.

## Usage

    pip install -e ".[dev]"
    scholarmend --input ../Trust-Evals-LitReview/corpus --out out

Tier 1 needs no configuration and resolves venue, year and track for 77% of a
Scholar corpus. Tier 2 needs an OpenReview account:

    export SCHOLARMEND_OPENREVIEW_USER='you@example.edu'
    export SCHOLARMEND_OPENREVIEW_PASSWORD='...'

Every response is written to `--cache` (default `.scholarmend-cache`). Commit
it: a rerun then reproduces byte-identically and makes no API calls.

    scholarmend --input ../Trust-Evals-LitReview/corpus --out out --offline

`--offline` fails loudly on a cache miss rather than reaching the network.

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

**What it does not recover: authors and abstracts.** Scholar truncates 71% of
author lists and effectively every abstract, and scholarmend leaves both as it
found them — measured over the corpus, they come from Scholar in 2,413 of 2,413
records. The RIS projection rewrites only `PY` and `JF`, so recovered authors
would have no consumer today. See the design document for what closing the gap
would take.

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
| …of which, venue determined **and verified against the reviewers' labels** | 90, zero per-record disagreements |
| …the other 14 | evidence retrieved automatically, final judgement not verified here — see below |
| Workshop status against reviewer labels (the 90) | zero disagreements |
| Scholar's year losing every disagreement | all 1,264 |
| Proceedings mining coverage | exactly 1,854 of 2,413 |
| Records with no miner at all | exactly 17 |
| Hand-maintained merge list | retired; 4 collapse at tier 1, 6 at tier 2 |

### What "settled" does and does not mean

The 104 figure counts records for which the miners extract something a live
resolver consumes — a venue directly, or an OpenReview forum id, a PMLR volume
or a PMC id. That is a claim about *reach*, not about correctness, and the two
halves of it are verified to different depths:

- **90 records** are settled *and checked*: their OpenReview `venueid` yields a
  venue, a year and a workshop verdict, and every one of the 90 agrees with the
  reviewers' hand-verified label. Zero disagreements, compared record by record.
- **14 records** are settled in the weaker sense. Ten resolve to PMLR volumes
  that are out of scope for this review — the Canadian Conference on AI, a
  workshop at ACML, an AAAI bridge programme — and for those the resolver
  deliberately declines to name a venue rather than coerce an unfamiliar
  conference onto a known one. It retrieves the proceedings title, which is the
  expensive part of the work, but a human still reads the result and makes the
  call. Three arrive via the PMC bridge, and one via a sibling proceedings URL.
- **8 records** have no automated route at all: NSF landing pages, Google Books
  chapters, an SPIE paper, a PDF on a personal page. These needed human
  judgement before and still do.

So the honest summary is that scholarmend **determines and verifies** the venue
for 90 of the 112, **gathers the evidence** for 14 more, and leaves 8 untouched.

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
