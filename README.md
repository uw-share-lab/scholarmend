# scholarmend

Recover true bibliographic metadata for Google Scholar exports, so that
screening tools reason over facts rather than over Scholar's truncations.

Status: **design approved, implementation not started.** See
`docs/superpowers/specs/2026-09-20-scholarmend-design.md`.

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
