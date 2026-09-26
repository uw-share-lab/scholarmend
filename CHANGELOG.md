# Changelog

## 0.1.0

First release on PyPI.

- Reads Google Scholar RIS exports and recovers venue, year, and track, mostly
  from the proceedings URL Scholar already put in each record. OpenReview,
  PMLR, PMC, and Semantic Scholar fill in what the URL alone can't.
- Writes `resolved.json` (every claim behind each field), `mended.ris` (the
  corrected RIS, ready for Covidence), and `report.txt` (what stayed
  unresolved, and why).
- Never drops a record and never guesses. A venue it can't determine keeps
  Scholar's value and is marked unresolved for a human to check.
- `--offline` replays a committed response cache and fails on a miss, so a
  rerun is reproducible.
- `--abstracts` replaces Scholar's snippet with the full abstract, but only
  when the source shows the record's own title.
- No runtime dependencies. Python 3.10 to 3.13.
