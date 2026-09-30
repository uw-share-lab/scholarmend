# Changelog

## 0.1.4

- `resolved.json` now carries OpenReview's `content.venue` as a
  `venue_string` claim (for example `ICLR 2022 Poster` or
  `ICLR 2022 Submitted`), verbatim, with the note's venueid as evidence. On
  OpenReview API v1 venue-years (ICLR up to 2023, NeurIPS 2021-22), a
  rejected paper carries the bare venueid too, so this string is the only
  place the decision shows. scholarmend passes it through without
  interpreting it. It is a claim only: the RIS projection is unchanged.
- Only forums fetched from now on carry it. Cache entries written before
  0.1.4 hold a venueid alone and are not refetched, so they give no
  `venue_string` claim. On the full 3,326-record corpus, `--offline` output
  (`resolved.json`, `mended.ris`, `report.txt`) is byte-identical to 0.1.3.

## 0.1.3

Documentation only; the code is unchanged from 0.1.2.

- The README, which is also the PyPI project description, no longer mentions
  venuetriage. It was never published, and its link was a relative path to a
  private repository, so it was broken on PyPI and GitHub alike.
- The `--abstracts` example no longer uses a path into that repository.

## 0.1.2

- `SCHOLARMEND_S2_KEY`, the Semantic Scholar API key, is now documented. The
  CLI has read it since 0.1.0, but the README and `--help` never mentioned it.
  `--help` now lists all three environment variables.
- The `--offline` help text now says what actually happens on a cache miss:
  the record falls back to tier 1 and the run exits 1.

## 0.1.1

- Semantic Scholar searches are spaced 1.1 seconds apart. With an API key
  (1 request per second), back-to-back searches were drawing 429s. Only real
  requests wait, so a run served from the cache is as fast as before.
- Every request now sends `scholarmend/<version>` and the repo URL as its
  User-Agent, instead of the default `Python-urllib`.
- New PyPI summary, matching the GitHub description.

Output is unchanged: on the full 3,326-record corpus, `resolved.json`,
`mended.ris` and `report.txt` are byte-identical to 0.1.0.

## 0.1.0

First release on PyPI.

- Reads Google Scholar RIS exports and recovers venue, year, and track, mostly
  from the proceedings URL Scholar already put in each record. OpenReview,
  PMLR, PMC, and Semantic Scholar fill in what the URL alone can't.
- OpenReview forums that were never moved to API v2, such as some 2022-2023
  workshops, are read from API v1 instead.
- A withdrawn or non-public OpenReview forum is cached as hidden, so a rerun
  doesn't ask again. Delete its cache entry to check whether it has since
  been made public.
- Writes `resolved.json` (every claim behind each field), `mended.ris` (the
  corrected RIS, ready for Covidence), and `report.txt` (what stayed
  unresolved, and why).
- Never drops a record and never guesses. A venue it can't determine keeps
  Scholar's value and is marked unresolved for a human to check.
- `--offline` replays a committed response cache and never reaches the
  network. A record whose lookup is missing from the cache falls back to
  URL-only resolution, and the run exits 1 so you know it was partial.
- `--abstracts` replaces Scholar's snippet with the full abstract, but only
  when the source shows the record's own title.
- No runtime dependencies. Python 3.10 to 3.13.
