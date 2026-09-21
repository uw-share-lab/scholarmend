# scholarmend — design

Recover true bibliographic metadata for Google Scholar search exports, so that
downstream screening tools reason over facts rather than over Scholar's
truncations.

Status: design approved 2026-09-20. Not yet implemented.

Every measurement below was taken against the Trust-Evals-LitReview screening
corpus. Paths of the form `corpus/*.ris`, `verification/` and `out/decisions.csv`
refer to that repository, which is the validation fixture for this package and
is not vendored here.

## The problem, measured

Google Scholar's `.ris` export is the industry standard input to systematic
reviews, and it is lossy in ways that are invisible until they corrupt a
result. Measured against the Trust-Evals-LitReview corpus (2,413 records, nine
exports, in `corpus/`):

| Defect | Rate |
|--------|------|
| Venue string ellipsized (`… Neural Information …`) | 2,375 / 2,413 (98%) |
| Author list truncated to five plus `...` | 1,713 / 2,413 (71%) |
| Records carrying a DOI | 2 / 2,413 (0.08%) |
| `PY` disagrees with the year in the record's own URL | 1,264 / 1,854 checkable (68%) |
| Abstract is a snippet with interior ellipses | effectively all |

A single record shows every defect at once:

    JF  - … Neural Information …
    AU  - ...
    PY  - 2026///
    UR  - https://proceedings.neurips.cc/paper_files/paper/2025/hash/4da4f3c0…-Abstract-Datasets_and_Benchmarks_Track.html

Scholar reports the venue as an ellipsis, the year as 2026, no track and no
DOI. The URL in the same record states NeurIPS, 2025, Datasets and Benchmarks
Track. **The ground truth was already in the file.**

This is not academic. Venue truncation misclassified 17 genuine ICML main-track
papers during venue triage on 2026-09-20, and 112 records escaped the rule table
entirely and were resolved by hand, via OpenReview lookups and a browser
session, over the course of a day.

### Why the obvious fix does not work

`refaudit`, the existing reference verifier, resolves against Crossref,
OpenAlex, DataCite, DOI content negotiation, arXiv, DBLP and OpenLibrary. Every
one of those is DOI-centric. This corpus contains two DOIs. Pointing refaudit at
it was measured at roughly 8% coverage and abandoned.

The identifier in this corpus is not a DOI. It is the **URL path**.

### Why not query a structured database instead?

Publish or Perish can search Crossref, OpenAlex, Semantic Scholar, Lens.org,
PubMed, Scopus and Web of Science directly. If any of them covered this corpus
well, acquisition could bypass Scholar entirely and resolution would be
unnecessary. Measured on a 30-title random sample of records whose true venue
and year are known from their URL:

| Source | Hit rate | Venue quality on hits |
|--------|----------|------------------------|
| OpenAlex | 19/30 (63%) | **0/19 returned a conference venue.** 8 returned `arXiv (Cornell University)`, 11 returned none. Year disagreed with the proceedings year in 6/19. |
| Semantic Scholar | 2/15 (13%, rate-limited floor) | correct venue and year on both hits |
| DBLP | unmeasured — the API was unreachable during testing | unknown; retest before relying on it |
| URL mining (tier 1) | **2,392/2,413 (99%)** | exact venue, year and track |

The mechanism is structural, not incidental. These are 2025–2026 papers. The
arXiv preprint carries a DOI; the proceedings version does not. A DOI-anchored
index therefore records the preprint and never links it to the published paper,
returning a record that is about the right paper but reports the wrong venue and
often the wrong year. That is worse than no answer, because it looks
authoritative.

The same mechanism produced the ten same-paper pairs with conflicting years
(preprint 2025 against proceedings 2026) recorded in
`verification/merge-titles-2026-09-20.csv`.

This finding is domain-specific and must not be over-generalised: PubMed is
excellent for medicine and Scopus and Web of Science for the social sciences.
It is 2025–2026 machine-learning conference output specifically that DOI-based
indexes serve badly. Sub-project A should therefore treat source fitness as a
per-domain property rather than querying every source uniformly.

Semantic Scholar is the exception worth keeping: its hit rate here is low but
its venue accuracy on hits was perfect, which makes it the appropriate tier-3
resolver for the 21 records no miner covers. An API key should be obtained, as
the unauthenticated rate limit depresses its measured hit rate.

## Goals

1. Recover venue, year, track, version and identifiers for Scholar records,
   preferring authoritative sources over Scholar in every case.
2. Retain every claim, with its source and evidence, so that provenance is
   auditable and PRISMA reporting can cite it.
3. Work offline and deterministically wherever the data permits, and reproduce
   byte-identically on a rerun months later.
4. Never silently drop or guess. An unresolvable record survives, flagged.

### Not delivered: authors and abstracts

An earlier draft of these goals also promised to recover the full author list
and the full abstract, and the problem statement above still reports that
Scholar truncates 71% of author lists. **scholarmend does not fix that.** No
component emits an `authors` or `abstract` claim; measured over the corpus, both
fields come from Scholar in 2,413 of 2,413 records.

This is deliberate rather than overlooked, but it was overlooked first: the
implementation plan's self-review checked that every file in the architecture
had a task and passed, without checking that every goal had one. The gap
surfaced only when the assembled pipeline was measured.

It stays unbuilt because it would currently buy nothing. The RIS projection
rewrites only `PY` and `JF` (see *Output*), so recovered authors would sit in
the canonical JSON with no consumer: Covidence and `venuetriage` both read the
RIS. Closing the gap properly means three changes together, not one — emitting
the fields (OpenReview's API already returns `authors` and `abstract` in a
note's `content`, and Semantic Scholar would need a wider field list),
extending the projection to rewrite `AU` and `AB`, and accepting the risk that
rewriting an author list — deleting N lines and inserting M — carries for the
byte-identical round-trip guarantee.

`PRECEDENCE` retains entries for `authors` and `abstract` so that policy exists
the day a resolver supplies them. Note that `openalex` appears there and has no
resolver at all.

## Non-goals

Searching, query fan-out and deduplication (sub-project A). Screening decisions
and PRISMA counting (`venuetriage`, sub-project C). Any user interface
(sub-project D). scholarmend takes records in and emits better records out.

## Architecture

    src/scholarmend/
    ├─ models.py      Record, Claim, Ledger, ResolvedRecord
    ├─ parse.py       RIS → Record (ported from venuetriage.parse)
    ├─ miners/        Tier 1 · offline, pure functions, zero network
    │   proceedings.py  proceedings.neurips.cc + proceedings.iclr.cc (shared grammar)
    │   openreview.py   openreview.net → forum id
    │   pmlr.py         mlresearch / mlr.press → volume number
    │   arxiv.py        arxiv.org → arXiv id
    ├─ resolvers/     Tier 2/3 · network, cached, opt-in
    │   openreview.py   forum id → venueid
    │   pmlr_index.py   volume → proceedings title
    │   pmc.py          PMC id → citation_volume
    │   semanticscholar.py          (dblp, openalex and crossref: see below)
    ├─ ledger.py      claim accumulation, precedence, confidence, conflicts
    ├─ cache.py       content-addressed on-disk store
    ├─ emit.py        canonical JSON + RIS projection
    └─ cli.py

Each layer is independently testable. Miners are pure `str -> list[Claim]`
functions requiring no network, which makes the majority of the system testable
with no fixtures beyond a URL string.

## Data model

    @dataclass(frozen=True)
    class Claim:
        field:      str    # year | venue | track | venue_id | version | doi | authors | abstract
        value:      str
        source:     str    # scholar | proceedings_url | openreview_api | pmlr_index | ...
        tier:       int    # 0..3
        confidence: float  # 0.0..1.0
        evidence:   str    # the exact URL or API path the value came from

A `Record` accumulates claims and never discards them. A `ResolvedRecord`
exposes the winning value per field together with every losing claim. Scholar's
incorrect `2026` is not a special case; it is a retained tier-0 claim that lost.

`Claim` is frozen and implements value equality, so claims are set-comparable
and deduplicable. (A mutable dataclass here caused a blocking defect during
venuetriage implementation; the same mistake is pre-empted.)

### `version` is a first-class field

`version` takes one of `preprint`, `proceedings` or `unknown`, and records which
artefact a claim describes. It exists because the dominant failure of tier-3
sources is not being wrong about the paper but being right about the *wrong
version of it*: OpenAlex matched 19 of 30 sampled titles and described the arXiv
preprint in every case where it named a venue at all.

Without this field, a tier-3 claim of "arXiv, 2024" competes directly against a
tier-1 claim of "NeurIPS, 2025" as though they were rival answers to one
question. They are not. They are correct answers about two different artefacts.
Making the distinction explicit means a preprint-sourced claim can contribute an
abstract and a full author list — which preprints legitimately have, and which
Scholar truncates — without ever competing for `venue` or `year`.

Determination, in precedence order:

| Evidence | `version` |
|----------|-----------|
| `proceedings.neurips.cc`, `proceedings.iclr.cc`, `proceedings.mlr.press` | `proceedings` |
| OpenReview `venueid` ending `/Conference` or a workshop id | `proceedings` |
| `arxiv.org`, or a DOI under the `10.48550` prefix | `preprint` |
| OpenReview forum with no resolved `venueid` | `unknown` |
| anything else | `unknown` |

**Boundary: scholarmend emits `version`; it does not merge on it.** Deduplication
belongs to sub-projects A and C.

### What actually retires the merge list

An earlier draft of this design proposed merging records whose `version` values
were `preprint` and `proceedings`. Measurement rejected that rule: of the six
title pairs in the corpus whose copies disagree on year, **none** is a preprint
paired with a proceedings record. Every one is a proceedings record paired with
an OpenReview record **carrying no year at all** — neither a `PY` field nor a
year in its URL. The rule would have fired on zero real cases.

What retires the list is not version but **resolved identity**. Once venue, year
and track come from authoritative sources, the two copies of a paper agree by
construction, and ordinary deduplication merges them with no special case.
Measured against the ten titles in `verification/merge-titles-2026-09-20.csv`:

| Mechanism | Titles | Why |
|-----------|--------|-----|
| Tier-1 URL mining alone | **4 / 10** | Scholar dated the copies 2025 and 2026; both URLs say 2025, so the dedup key matches once mined |
| Tier-2 OpenReview `venueid` | **6 / 10** | the OpenReview copy carries no year anywhere; the `venueid` supplies it |
| remaining manual | **0 / 10** | |

This mirrors, from the other side, the behaviour already recorded for Covidence:
it removed the six year-less pairs on import, because it treats a missing year
permissively, and kept the four carrying conflicting years. scholarmend resolves
precisely the four Covidence cannot, and tier 2 resolves the six it handles only
by accident of a permissive rule.

The guarantee venuetriage established is preserved. Its dedup key includes the
year so that a genuine workshop-then-conference pair is never collapsed. Identity
resolution strengthens that rather than weakening it: a workshop paper resolves
to `ICML.cc/2024/Workshop/FOO` and its conference version to
`ICML.cc/2025/Conference`, which are different identities and do not merge.
Merging on a guess deletes a paper silently and nothing downstream recovers it,
so identity must come from a resolved claim, never from a similarity score.

## Tiers

A tier runs **per field, not per record**. A record whose URL already yields
venue, year and track makes no network call for those fields even if its
abstract remains unresolved. This is what keeps the ledger's cost equal to a
plain cascade's.

Escalation from tier N to tier N+1 happens for a field when it has no claim, or
when its best claim has confidence below **0.80**. That threshold is an initial
value, refitted against the gold set during validation and then frozen as data
alongside the precedence table.

| Tier | Sources | Cost | Coverage on this corpus |
|------|---------|------|--------------------------|
| 0 | Scholar's own RIS fields | free | 100%, lowest precedence, always retained |
| 1 | Offline URL miners | free, deterministic | **99% yield a key; 77% fully resolved** |
| 2 | Identifier-keyed APIs: OpenReview `venueid`, PMLR index, PMC | cached network | the 22% holding OpenReview forum ids |
| 3 | Fuzzy title match: Semantic Scholar | cached network | remainder, always flagged low-confidence |

Only Semantic Scholar was built at tier 3. DBLP was unreachable during the
measurements above and remains unmeasured; OpenAlex was measured and rejected,
because it described the arXiv preprint rather than the published paper in every
case where it named a venue at all; Crossref shares that DOI-centric weakness on
this corpus. `PRECEDENCE` still lists `openalex` for `authors` and `abstract`,
where a preprint's values are legitimate, so the policy exists the day a
resolver supplies them.

Tier-1 breakdown, measured:

| Miner | Records | Yield |
|-------|---------|-------|
| `proceedings.py` (NeurIPS 1,264 + ICLR 590) | 1,854 | venue, year, track — complete |
| `openreview.py` | 527 | forum id — requires tier 2 |
| `pmlr.py` | 11 | volume number — requires tier 2 |
| none | 21 | manual floor |

### The proceedings grammar

NeurIPS and ICLR share one path grammar, so one miner serves both:

    https://proceedings.{neurips|iclr}.cc/paper_files/paper/{year}/hash/{hash}-Abstract-{Track}.html

`{Track}` is a closed vocabulary, and it differs by host:

| Host | Tracks observed | Records |
|------|-----------------|---------|
| `proceedings.neurips.cc` | `Conference` 1,056, `Datasets_and_Benchmarks_Track` 176, `Position_Paper_Track` 30, `Creative_AI_Track` 2 | 1,264 |
| `proceedings.iclr.cc` | `Conference` 590 | 590 |

**All observed tracks are main track.** Workshop papers are never hosted at
these paths, which is why the signal discriminates so cleanly.

The miner must tolerate query strings: one URL in the corpus carries
`?utm_source=chatgpt.com`, having been round-tripped through a chatbot before
reaching Scholar. Parsing must strip the query before matching, and a fixture
must preserve this case.

An unrecognised `{Track}` value must fail loudly rather than be treated as main
track, so that a future track addition surfaces as an error rather than a silent
misclassification.

## Precedence is measured, not declared

The precedence table lives in `ledger.py` as data, in the manner of
`venuetriage/rules.py`, and is fitted against the gold set rather than assumed.
The initial hypothesis follows directly from the corpus measurements:

| Field | Precedence | Evidence |
|-------|-----------|----------|
| `year` | proceedings URL > OpenReview > Scholar | Scholar loses 1,264 / 1,264 disagreements |
| `venue`, `track` | OpenReview `venueid` > proceedings URL host > Scholar `JF` | 92 / 92 correct in the hand-checked sample |
| `authors`, `abstract` | any structured source > Scholar, **including `preprint` sources** | Scholar truncates 71% and ~100% respectively |
| `venue`, `year` | claims marked `version: preprint` are **excluded entirely**, not merely outranked | OpenAlex named a venue for 8 of 19 matched titles and was describing the preprint in all 8 |

Independent agreement raises confidence. Disagreement at the same or adjacent
tier flags the record `conflict` and reports it; precedence still applies, but
never silently.

## Reproducibility

The cache is content-addressed, on disk, and committed to the repository. A
rerun months later reproduces byte-identically and issues zero API calls, which
is what allows reproducibility to be asserted in a methods section rather than
hoped for.

`--offline` hard-fails on a cache miss. Silent network access under a flag that
promises determinism would invalidate the claim the flag exists to make.

## Output

Canonical JSON is the real output: one object per record, every field carrying
value, source, tier, confidence and evidence, alongside the full claim ledger.

RIS is a **projection** of that JSON, emitted for Covidence and `venuetriage`,
which cannot represent provenance. The projection must round-trip
byte-identically for fields scholarmend does not touch.

## Validation

The 2026-09-20 verification effort produced a labelled gold set, committed in
`verification/`. It is the acceptance criterion.

**Headline test: of the 112 records that required human resolution, scholarmend
provides an automated resolution path for at least 103.**

That is a claim about reach, and it must not be bundled with the separate,
stronger claim about correctness. Stated precisely, and as the shipped suite
verifies them:

- **reach** — at least 103 of the 112 yield something a live resolver consumes
  (measured: 104). Asserted by running the real miners over records joined to
  the corpus, not by inspecting the labels.
- **correctness** — for the 90 reached through an OpenReview `venueid`, the
  predicted workshop-or-main verdict agrees with the reviewers' label for every
  single record. Zero disagreements, compared one record at a time, because two
  errors in opposite directions would still sum to the right totals.

The remaining 14 are reached but not checked against truth by this suite. Ten
resolve to PMLR volumes outside this review's scope, where the resolver
deliberately declines to name a venue and emits only the proceedings title as
evidence for a human. The suite is hermetic and offline, so verifying those
predictions would require their lookups to be committed into the cache first.

103 is not aspirational. It is the count actually reached by hand, so the test
asserts that the pipeline reproduces a day of human work.

Predicted disposition of the 112:

| Bucket | n | Tier | Deterministic |
|--------|---|------|---------------|
| `openreview.net` with forum id | 90 | 2 | yes |
| `raw.githubusercontent.com/mlresearch/vNNN` | 10 | 1 → 2 | yes |
| `pmc.ncbi.nlm.nih.gov` volume → PMLR | 3 | 2 | yes |
| NSF, Google Books, SPIE, IEEE, personal pages | 9 | 3 or manual | partial |

Four regression suites, all built from committed files:

1. `verification/openreview-venues.json` — 90 forum→`venueid` pairs. The tier-2
   resolver must reproduce all 90.
2. `verification/review-bucket-resolutions.json` — 112 labelled `truth` values.
   Measures the headline number.
3. `out/decisions.csv` — 1,759 deduplicated records with `final_verdict`
   (1,391 MAIN / 368 WORKSHOP). End to end, no verdict may flip without an
   explicit recorded reason.
4. `verification/merge-titles-2026-09-20.csv` and `overrides-2026-09-20.csv` —
   10 merges and 7 per-record rulings that must survive unchanged.

**Secondary acceptance test: the hand-maintained merge list becomes
unnecessary.** All ten titles must be merged by resolved identity alone — four
from tier-1 mining, six from tier-2 `venueid` — with the list retained only as a
regression fixture. A hand-maintained list of paper titles is a maintenance
burden that grows with every future search; retiring it is a durable win rather
than a one-off correction.

Plus one property test the corpus supplies free: **Scholar's `PY` must lose all
1,264 year disagreements.** A single URL-derived year losing to Scholar means
the precedence table is wrong.

## Error handling

The asymmetry established during venue triage carries over: a false drop is
silent and unrecoverable, a false keep is caught later at screening.

| Failure | Behaviour |
|---------|-----------|
| No source resolves a field | Retain Scholar's value, mark `unresolved`, flag. Never drop, never guess. |
| Two sources disagree | Apply precedence, flag `conflict`, surface in the report. Never silently pick. |
| Network or API error | Fall back to cache, then to the offline value. Degrade; never crash a 2,400-record run. |
| Authentication fails | Report clearly, continue tier-1 only, exit non-zero. A partial run must announce itself. |
| Cache miss under `--offline` | Hard fail. |
| Unrecognised track token in a proceedings URL | Hard fail. |

## Testing

Test-driven throughout. Fixtures are drawn from the real corpus rather than
invented, and assert their own real-world quirks — venuetriage's Task 1
established that a round-trip test alone cannot detect fixture corruption, and
the corresponding fixture-integrity test is replicated here. Miners are pure
functions tested offline against URL strings. The RIS projection is verified
byte-identical on untouched fields.

## Risks

1. **OpenReview authentication may not clear the challenge.** Anonymous reads
   return `403 ChallengeRequiredError`; `POST /login` exists and requires
   `{id, password}`. That a login token unblocks `/notes` is **verified only as
   far as the endpoint accepting credentials** — it has not been proven end to
   end. This gates 90 of the 112 records. *Mitigation: the first implementation
   task is a spike proving it. If it fails, a one-time authenticated browser
   capture writes the same data into the committed cache; reproducibility is
   unaffected and only convenience is lost.*
2. **URL grammars drift.** NeurIPS has changed its path scheme historically.
   *Mitigation: miners are data-driven, version-pinned, and fail loudly rather
   than returning nothing.*
3. **Rate limiting.** OpenReview limited the hand-driven effort at roughly 150
   calls. *Mitigation: 527 forum lookups is a one-time cost paid into a
   committed cache, with backoff and resume.*
4. **`OUT_OF_SCOPE` is a third verdict** present in the labels but absent from
   venuetriage's binary MAIN/WORKSHOP split. scholarmend carries it through as
   data; sub-project C decides its treatment.
5. **The 27% fetch redundancy is not scholarmend's to fix** — 2,413 records
   reduce to 1,759 unique titles because nine overlapping venue-alias searches
   were run by hand. That belongs to sub-project A. scholarmend stamps
   provenance so that A can later prove its fan-out complete.

## Relationship to the wider effort

scholarmend is sub-project B of four, agreed 2026-09-20:

- **A · Acquisition** — venue registry, alias fan-out, result-cap slicing, and a
  source registry carrying per-domain fitness. The measurements above show that
  querying every available source uniformly is wrong: for this corpus OpenAlex
  returns the preprint and Scholar plus a parseable URL wins, while for medicine
  or the social sciences the ranking reverses.
- **B · Resolution** — this document.
- **C · Screening** — `venuetriage`, already shipped. Consumes B's output; its
  rule table should shrink, since much of it exists to guess around truncation.
- **D · Interface** — results grid, metrics, review queue, export.

Build order B → A → C → D. B first because it is validated against an existing
gold set, carries no terms-of-service risk, and makes the remaining three
worth building.
