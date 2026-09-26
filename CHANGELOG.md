# Changelog

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
