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

## Relationship to other tools

- [`venuetriage`](../Trust-Evals-LitReview) — consumes scholarmend's output to
  separate workshop from main-track papers before Covidence.
- [`refaudit`](https://github.com/uw-share-lab/refaudit) — verifies a finished
  bibliography against Crossref, OpenAlex and arXiv. Different job, different
  input; its DOI-centric resolvers reach only ~8% coverage on this corpus.

## Licence

MIT.
