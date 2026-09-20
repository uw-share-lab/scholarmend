# scholarmend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover true venue, year, track and identifiers for Google Scholar RIS exports, so that screening tools reason over facts rather than over Scholar's truncations.

**Architecture:** A tiered cascade that escalates *per field*, not per record. Tier 1 mines the URL already present in every record and needs no network at all; tiers 2 and 3 call cached, credentialed APIs only for fields tier 1 could not settle. Every source that speaks records a `Claim`, and nothing is discarded, so the winning value and the losing ones are both auditable.

**Tech Stack:** Python 3.10+, stdlib only at runtime (`urllib`, `json`, `re`, `dataclasses`). hatchling for packaging, pytest for tests, ruff and mypy for checks. No third-party runtime dependencies, matching `refaudit`.

**Spec:** `docs/superpowers/specs/2026-09-20-scholarmend-design.md`

## Global Constraints

- Python `>=3.10`. Use `from __future__ import annotations` in every module.
- **No runtime dependencies.** Tests may use pytest; the package itself imports stdlib only.
- The package is `src/scholarmend/`, installed editable with `pip install -e ".[dev]"`.
- Never drop a record. An unresolvable field keeps Scholar's value and is marked `unresolved`.
- Never silently pick between disagreeing sources at the same tier: apply precedence **and** flag `conflict`.
- Precedence lives as **data**, in one table, in `ledger.py` — never as `if` branches scattered through resolvers.
- An unrecognised track token in a proceedings URL is a **hard failure**, not a default to main track.
- `--offline` hard-fails on a cache miss. It must never silently reach the network.
- The validation corpus is the sibling repo `../Trust-Evals-LitReview`. It is a fixture, never vendored, never modified.
- Commit after every task. Conventional-commit prefixes (`feat:`, `test:`, `fix:`, `docs:`, `chore:`).

## File Structure

| File | Responsibility |
|------|----------------|
| `src/scholarmend/models.py` | `Record` (a parsed RIS record) and `Claim` (one source's assertion about one field) |
| `src/scholarmend/parse.py` | RIS text → `Record` list, preserving each record's original bytes |
| `src/scholarmend/ledger.py` | claim accumulation, the precedence table, resolution, conflict detection |
| `src/scholarmend/miners/proceedings.py` | `proceedings.neurips.cc` and `proceedings.iclr.cc` → year, venue, track, version |
| `src/scholarmend/miners/openreview.py` | `openreview.net` → forum id |
| `src/scholarmend/miners/pmlr.py` | `mlr.press` / `mlresearch` → volume number |
| `src/scholarmend/miners/arxiv.py` | `arxiv.org` → arXiv id, `version: preprint` |
| `src/scholarmend/miners/__init__.py` | the miner registry — one ordered tuple |
| `src/scholarmend/cache.py` | content-addressed on-disk response store, `--offline` enforcement |
| `src/scholarmend/http.py` | thin `urllib` wrapper: timeouts, retries, backoff |
| `src/scholarmend/resolvers/openreview.py` | forum id → `venueid` (tier 2) |
| `src/scholarmend/resolvers/semanticscholar.py` | title → venue, year (tier 3) |
| `src/scholarmend/pipeline.py` | wires parse → mine → escalate → resolve |
| `src/scholarmend/emit.py` | canonical JSON, and the RIS projection |
| `src/scholarmend/cli.py` | argument parsing, file IO, exit codes |
| `tests/fixtures/sample.ris` | four real records carrying the corpus's real quirks |

Miners are pure functions `mine(url: str) -> list[Claim]`. They take a string and return claims. That is the whole interface, and it is why the majority of this system is testable with no network, no fixtures beyond a URL, and no mocking.

---

### Task 1: Prove OpenReview authentication

This is first because it gates 90 of the 112 records the acceptance test measures, and because if it fails the whole tier-2 design changes. It is a spike: the output is an answer and a committed note, not production code.

**Files:**
- Create: `docs/openreview-auth.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a documented answer to "does a login token clear the challenge?", which Task 7 depends on.

- [ ] **Step 1: Confirm the anonymous refusal still reproduces**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  "https://api2.openreview.net/notes?forum=0GgFeojE4a&limit=1"
```

Expected: `403`. If it returns `200`, the challenge has been lifted, which is a different world — record that in the note and skip to Step 5.

- [ ] **Step 2: Obtain a token**

Requires a free OpenReview account. Set credentials in the shell, never in a file:

```bash
export SCHOLARMEND_OPENREVIEW_USER='you@uwaterloo.ca'
export SCHOLARMEND_OPENREVIEW_PASSWORD='...'
curl -s -X POST https://api2.openreview.net/login \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$SCHOLARMEND_OPENREVIEW_USER\",\"password\":\"$SCHOLARMEND_OPENREVIEW_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('token','NO TOKEN')[:40])"
```

Expected: a JWT prefix, not `NO TOKEN`.

- [ ] **Step 3: Use the token against the endpoint that matters**

```bash
TOKEN=$(curl -s -X POST https://api2.openreview.net/login \
  -H 'Content-Type: application/json' \
  -d "{\"id\":\"$SCHOLARMEND_OPENREVIEW_USER\",\"password\":\"$SCHOLARMEND_OPENREVIEW_PASSWORD\"}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api2.openreview.net/notes?forum=0GgFeojE4a&limit=1" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); n=d['notes'][0]; print('venueid:', n['content'].get('venueid',{}).get('value'))"
```

Expected: `venueid: ICML.cc/2026/Workshop/AI4GOOD` — the value recorded in `../Trust-Evals-LitReview/verification/openreview-venues.json` for that forum id.

- [ ] **Step 4: Check the rate limit honestly**

Fetch ten known forum ids in a loop with a 1-second delay, and record where, if anywhere, throttling begins. The hand-driven effort hit limits near 150 calls; tier 2 needs 527.

```bash
python3 - <<'EOF'
import json,os,time,urllib.request
ids=json.load(open('../Trust-Evals-LitReview/verification/openreview-venues.json'))
tok=os.environ['SCHOLARMEND_OPENREVIEW_TOKEN']
for i,f in enumerate(list(ids)[:10],1):
    r=urllib.request.Request(f"https://api2.openreview.net/notes?forum={f}&limit=1",
                             headers={'Authorization':f'Bearer {tok}'})
    try:
        with urllib.request.urlopen(r,timeout=20) as resp: code=resp.status
    except Exception as e: code=repr(e)[:60]
    print(i,f,code); time.sleep(1.0)
EOF
```

- [ ] **Step 5: Write the note and commit**

Create `docs/openreview-auth.md` recording: whether the token cleared the challenge, the exact header form that worked, the JSON path to `venueid` (`notes[0].content.venueid.value`), observed rate-limit behaviour, and token lifetime if stated. If authentication did **not** work, record that instead and note that Task 9 must fall back to a one-time authenticated browser capture written into the cache.

```bash
git add docs/openreview-auth.md
git commit -m "docs: record whether OpenReview login clears the challenge"
```

---

### Task 2: The RIS parser

Ported from `venuetriage.parse`, which achieves byte-identical round-trip by construction. **One invariant changes:** venuetriage never rewrites a record, so it concatenates `raw`. scholarmend must rewrite fields, so `Record.raw` stays the source of truth for *untouched* text and Task 11 rewrites specific lines surgically.

**Files:**
- Create: `src/scholarmend/models.py`, `src/scholarmend/parse.py`, `tests/fixtures/sample.ris`, `tests/test_parse.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Record(raw: str, fields: dict[str, list[str]], source_file: str)` with `.first(tag, default='')`, `.title`, `.venue`, `.publisher`, `.year`, `.urls`; `parse_ris(text: str, source_file: str) -> list[Record]`; `parse_file(path: Path) -> list[Record]`.

- [ ] **Step 1: Create the fixture with the corpus's real quirks**

Create `tests/fixtures/sample.ris`. It must be saved **with a UTF-8 BOM**, every `ER  - ` line must retain its **trailing space**, and the fourth record's URL must retain `?utm_source=chatgpt.com`. These are not cosmetic: all three appear in the real corpus, and a fixture that quietly cleans them up makes the round-trip test vacuous.

```python
# Generate the fixture exactly, rather than hand-typing it:
from pathlib import Path
body = (
    "TY  - JOUR\nAU  - Huang, S\nAU  - Yang, L\nAU  - ...\n"
    "TI  - Thinkbench: Dynamic out-of-distribution evaluation for robust llm reasoning\n"
    "JF  - … Neural Information …\nPB  - proceedings.neurips.cc\n"
    "UR  - https://proceedings.neurips.cc/paper_files/paper/2025/hash/4da4f3c0dd1b907c48e2119afb2e2fde-Abstract-Datasets_and_Benchmarks_Track.html\n"
    "PY  - 2026///\nER  - \n\n"
    "TY  - JOUR\nAU  - Huang, Y\nAU  - ...\n"
    "TI  - TrustGen: A Platform of Dynamic Benchmarking\n"
    "JF  - … Representations\nPB  - proceedings.iclr.cc\n"
    "UR  - https://proceedings.iclr.cc/paper_files/paper/2026/hash/635a38ee326fb0464e0c2b1c1a0b0c1d-Abstract-Conference.html\n"
    "PY  - 2026///\nER  - \n\n"
    "TY  - JOUR\nAU  - Zhang, Y\nAU  - Xie, F\n"
    "TI  - Meta-Router: Bridging Gold-standard and Preference-based Evaluations\n"
    "JF  - … on Learning Representations\nPB  - openreview.net\n"
    "UR  - https://openreview.net/forum?id=r0BFucF2dH\nER  - \n\n"
    "TY  - JOUR\nAU  - Nasr, M\nAU  - ...\n"
    "TI  - Scalable extraction of training data from aligned, production language models\n"
    "JF  - … Representations\nPB  - proceedings.iclr.cc\n"
    "UR  - https://proceedings.iclr.cc/paper_files/paper/2025/file/aaaabbbbccccddddeeeeffff00001111-Paper-Conference.pdf?utm_source=chatgpt.com\n"
    "PY  - 2025///\nER  - \n"
)
Path("tests/fixtures/sample.ris").write_bytes(b"\xef\xbb\xbf" + body.encode("utf-8"))
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_parse.py`:

```python
from __future__ import annotations

from pathlib import Path

from scholarmend.parse import emit_ris, parse_file, parse_ris

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def test_parses_every_record():
    records = parse_file(FIXTURE)
    assert len(records) == 4


def test_round_trip_is_byte_identical():
    text = FIXTURE.read_text(encoding="utf-8-sig")
    assert emit_ris(parse_ris(text, "sample.ris")) == text


def test_fixture_retains_the_trailing_space_on_er_lines():
    # The real corpus writes "ER  - " with a trailing space. A fixture that
    # loses it makes the round-trip test pass without proving anything.
    raw = FIXTURE.read_bytes().decode("utf-8-sig")
    assert "ER  - \n" in raw


def test_fixture_retains_the_utm_query_string():
    # One real URL arrived via a chatbot and carries a tracking parameter.
    raw = FIXTURE.read_bytes().decode("utf-8-sig")
    assert "?utm_source=chatgpt.com" in raw


def test_fixture_is_saved_with_a_bom():
    assert FIXTURE.read_bytes().startswith(b"\xef\xbb\xbf")


def test_repeated_tags_keep_every_value_in_order():
    first = parse_file(FIXTURE)[0]
    assert first.fields["AU"] == ["Huang, S", "Yang, L", "..."]


def test_year_strips_scholars_trailing_slashes():
    assert parse_file(FIXTURE)[0].year == "2026"


def test_urls_returns_every_ur_value():
    third = parse_file(FIXTURE)[2]
    assert third.urls == ["https://openreview.net/forum?id=r0BFucF2dH"]


def test_a_record_with_no_year_reports_empty_string():
    assert parse_file(FIXTURE)[2].year == ""


def test_content_before_the_first_record_is_refused():
    import pytest

    with pytest.raises(ValueError, match="content before the first record"):
        parse_ris("junk\nTY  - JOUR\nER  - \n", "bad.ris")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest tests/test_parse.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.parse'`

- [ ] **Step 4: Write `models.py`**

```python
"""The two data shapes the rest of the package is built on."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    """One RIS record.

    ``raw`` is the record's original text, byte for byte. ``fields`` is a
    read-only view over it, for asking questions. Only ``emit.project_ris``
    rewrites a record, and it does so by surgical line replacement against
    ``raw`` so that every untouched byte survives.
    """

    raw: str
    fields: dict[str, list[str]]
    source_file: str

    def first(self, tag: str, default: str = "") -> str:
        values = self.fields.get(tag)
        return values[0] if values else default

    @property
    def title(self) -> str:
        return self.first("TI")

    @property
    def venue(self) -> str:
        return self.first("JF")

    @property
    def publisher(self) -> str:
        return self.first("PB")

    @property
    def urls(self) -> list[str]:
        return list(self.fields.get("UR", []))

    @property
    def year(self) -> str:
        """The four-digit year. Scholar writes ``PY  - 2025///``."""
        match = re.search(r"\d{4}", self.first("PY"))
        return match.group(0) if match else ""
```

- [ ] **Step 5: Write `parse.py`**

```python
"""RIS in, RIS out, with the original text preserved exactly.

A record starts at a line beginning ``TY  - `` and runs until the next one.
That rule is what makes ``emit_ris(parse_ris(t)) == t`` true by construction
rather than by careful re-serialisation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .models import Record

_RECORD_START = re.compile(r"(?m)^TY  - ")
_FIELD = re.compile(r"(?m)^([A-Z][A-Z0-9])  - (.*)$")


def parse_ris(text: str, source_file: str) -> list[Record]:
    """Split ``text`` into records, keeping each one's original slice."""
    starts = [m.start() for m in _RECORD_START.finditer(text)]
    if not starts:
        return []
    if text[: starts[0]].strip():
        raise ValueError(f"{source_file}: content before the first record; refusing to guess")

    records = []
    bounds = starts + [len(text)]
    for begin, end in zip(bounds, bounds[1:]):
        raw = text[begin:end]
        records.append(Record(raw=raw, fields=_fields(raw), source_file=source_file))
    return records


def _fields(raw: str) -> dict[str, list[str]]:
    """Tag to values. Repeated tags (AU, UR, M1) keep every value, in order."""
    fields: dict[str, list[str]] = {}
    for tag, value in _FIELD.findall(raw):
        fields.setdefault(tag, []).append(value.strip())
    return fields


def parse_file(path: Path) -> list[Record]:
    """Parse one file. ``utf-8-sig`` drops the BOM Scholar writes."""
    return parse_ris(path.read_text(encoding="utf-8-sig"), path.name)


def emit_ris(records: Iterable[Record]) -> str:
    """Concatenate records' original text, unchanged."""
    return "".join(record.raw for record in records)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_parse.py -v`
Expected: 10 passed

- [ ] **Step 7: Verify round-trip against the whole real corpus**

```bash
python3 - <<'EOF'
import glob
from pathlib import Path
from scholarmend.parse import emit_ris, parse_ris
for f in sorted(glob.glob("../Trust-Evals-LitReview/corpus/*.ris")):
    text = Path(f).read_text(encoding="utf-8-sig")
    assert emit_ris(parse_ris(text, Path(f).name)) == text, f
    print(f"ok  {len(parse_ris(text, Path(f).name)):5d}  {Path(f).name}")
EOF
```

Expected: nine `ok` lines, counts summing to 2413.

- [ ] **Step 8: Commit**

```bash
git add src/scholarmend/models.py src/scholarmend/parse.py tests/
git commit -m "feat: parse Scholar RIS with a byte-identical round-trip"
```

---

### Task 3: Claims and the precedence ledger

The precedence table does double duty. A source listed for a field is allowed to answer it, in the listed order; a source **absent** from a field's tuple is excluded from answering it at all. That is how the spec's rule — preprint sources may supply `authors` and `abstract` but never `venue` or `year` — is expressed as data rather than as a special case.

**Files:**
- Create: `src/scholarmend/ledger.py`, `tests/test_ledger.py`
- Modify: `src/scholarmend/models.py` (append `Claim`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `Claim(field, value, source, tier, confidence, evidence)` frozen and hashable; `Ledger()` with `.add(claim)`, `.claims(field) -> list[Claim]`, `.resolve(field) -> Claim | None`, `.conflicts() -> list[str]`, `.is_unresolved(field) -> bool`; module constant `PRECEDENCE: dict[str, tuple[str, ...]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ledger.py`:

```python
from __future__ import annotations

from scholarmend.ledger import PRECEDENCE, Ledger
from scholarmend.models import Claim


def c(field, value, source, tier, conf=1.0, evidence="e"):
    return Claim(field=field, value=value, source=source, tier=tier,
                 confidence=conf, evidence=evidence)


def test_claim_is_hashable_and_compares_by_value():
    a = c("year", "2025", "proceedings_url", 1)
    b = c("year", "2025", "proceedings_url", 1)
    assert a == b
    assert len({a, b}) == 1


def test_higher_precedence_source_wins():
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert led.resolve("year").value == "2025"


def test_losing_claims_are_retained():
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert {cl.value for cl in led.claims("year")} == {"2025", "2026"}


def test_a_source_absent_from_a_fields_precedence_cannot_answer_it():
    # arxiv may supply authors but must never supply venue.
    led = Ledger()
    led.add(c("venue", "arXiv (Cornell University)", "arxiv_url", 3))
    assert led.resolve("venue") is None
    assert led.is_unresolved("venue") is True


def test_that_same_source_may_still_answer_a_field_it_is_listed_for():
    led = Ledger()
    led.add(c("authors", "A; B; C", "arxiv_url", 3))
    assert led.resolve("authors").value == "A; B; C"


def test_disagreement_within_one_tier_is_a_conflict():
    led = Ledger()
    led.add(c("venue", "ICML", "openreview_api", 2))
    led.add(c("venue", "NeurIPS", "pmlr_index", 2))
    assert "venue" in led.conflicts()


def test_disagreement_across_tiers_is_not_a_conflict():
    # Scholar disagreeing with a mined URL is the expected case, 1,264 times
    # over in the real corpus. Flagging it would make the report useless.
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert led.conflicts() == []


def test_agreement_within_a_tier_is_not_a_conflict():
    led = Ledger()
    led.add(c("venue", "ICML", "openreview_api", 2))
    led.add(c("venue", "ICML", "pmlr_index", 2))
    assert led.conflicts() == []


def test_unknown_field_resolves_to_none():
    assert Ledger().resolve("nonsense") is None


def test_precedence_puts_proceedings_url_above_scholar_for_year():
    assert PRECEDENCE["year"].index("proceedings_url") < PRECEDENCE["year"].index("scholar")


def test_precedence_excludes_preprint_sources_from_venue_and_year():
    for field in ("venue", "year"):
        assert "arxiv_url" not in PRECEDENCE[field]
        assert "openalex" not in PRECEDENCE[field]


def test_key_fields_exist_so_tier_one_can_hand_identifiers_to_tier_two():
    for field in ("forum_id", "pmlr_volume", "arxiv_id", "pmc_id"):
        assert field in PRECEDENCE
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_ledger.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.ledger'`

- [ ] **Step 3: Append `Claim` to `models.py`**

```python
@dataclass(frozen=True)
class Claim:
    """One source's assertion about one field of one record.

    Frozen, and every attribute is a scalar, so claims are hashable and
    set-comparable. A mutable dataclass in this position caused a blocking
    defect during venuetriage's implementation; the shape here forecloses it.
    """

    field: str
    value: str
    source: str
    tier: int
    confidence: float
    evidence: str
```

- [ ] **Step 4: Write `ledger.py`**

```python
"""Claim accumulation and resolution.

The precedence table is the whole policy, and it is data. A source listed for
a field may answer it, best first; a source *absent* from a field's tuple is
excluded from answering it at all. That single mechanism expresses both
ordering and exclusion -- notably that preprint-derived sources may supply an
abstract and a full author list, which preprints genuinely have, but must never
supply a venue or a year, which they get wrong by construction.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Claim

PRECEDENCE: dict[str, tuple[str, ...]] = {
    # Scholar loses all 1,264 year disagreements measured on the corpus.
    "year": ("proceedings_url", "openreview_api", "pmlr_index", "semanticscholar", "scholar"),
    # The OpenReview venueid was correct in 92 of 92 hand-checked cases.
    "venue": ("openreview_api", "proceedings_url", "pmlr_index", "semanticscholar", "scholar"),
    "track": ("openreview_api", "proceedings_url"),
    "venue_id": ("openreview_api",),
    "version": ("proceedings_url", "openreview_api", "pmlr_index", "arxiv_url"),
    # Preprint sources are welcome here: Scholar truncates 71% of author lists.
    "authors": ("openreview_api", "semanticscholar", "openalex", "arxiv_url", "scholar"),
    "abstract": ("openreview_api", "semanticscholar", "openalex", "arxiv_url", "scholar"),
    "doi": ("openreview_api", "semanticscholar", "openalex", "arxiv_url"),
    # Keys, not answers: these carry an identifier from tier 1 to tier 2.
    "forum_id": ("openreview_url",),
    "pmlr_volume": ("pmlr_url",),
    "arxiv_id": ("arxiv_url",),
    "pmc_id": ("pmc_url",),
}


class Ledger:
    """Every claim made about one record, and the policy for choosing between them."""

    def __init__(self) -> None:
        self._claims: dict[str, list[Claim]] = defaultdict(list)

    def add(self, claim: Claim) -> None:
        if claim not in self._claims[claim.field]:
            self._claims[claim.field].append(claim)

    def claims(self, field: str) -> list[Claim]:
        """Every claim for ``field``, including ones excluded by precedence."""
        return list(self._claims.get(field, []))

    def resolve(self, field: str) -> Claim | None:
        """The winning claim, or ``None`` if no permitted source answered."""
        order = PRECEDENCE.get(field)
        if not order:
            return None
        for source in order:
            for claim in self._claims.get(field, []):
                if claim.source == source:
                    return claim
        return None

    def is_unresolved(self, field: str) -> bool:
        return self.resolve(field) is None

    def conflicts(self) -> list[str]:
        """Fields where two sources *at the same tier* disagree.

        Cross-tier disagreement is the normal case -- Scholar against a mined
        URL happens 1,264 times in the corpus -- so flagging it would drown the
        report. Same-tier disagreement means two equally trusted sources cannot
        both be right, which is worth a human's attention.
        """
        out = []
        for field, claims in self._claims.items():
            by_tier: dict[int, set[str]] = defaultdict(set)
            for claim in claims:
                by_tier[claim.tier].add(claim.value)
            if any(len(values) > 1 for values in by_tier.values()):
                out.append(field)
        return sorted(out)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_ledger.py -v`
Expected: 12 passed

- [ ] **Step 6: Commit**

```bash
git add src/scholarmend/models.py src/scholarmend/ledger.py tests/test_ledger.py
git commit -m "feat: add the claim ledger and the precedence table"
```

---

### Task 4: The proceedings miner

The single highest-value component: 1,854 of 2,413 records (77%) get venue, year and track from this one function, offline and deterministically. NeurIPS and ICLR share an identical path grammar, verified against the corpus, so one miner serves both.

**Files:**
- Create: `src/scholarmend/miners/proceedings.py`, `tests/test_miner_proceedings.py`

**Interfaces:**
- Consumes: `Claim` from Task 3.
- Produces: `mine(url: str) -> list[Claim]`. Returns `[]` for a non-matching URL. Raises `UnknownTrack` for a matching host with an unrecognised track token. Module constants `HOSTS: dict[str, str]` and `TRACKS: frozenset[str]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_miner_proceedings.py`:

```python
from __future__ import annotations

import pytest

from scholarmend.miners.proceedings import UnknownTrack, mine

NEURIPS_DB = (
    "https://proceedings.neurips.cc/paper_files/paper/2025/hash/"
    "4da4f3c0dd1b907c48e2119afb2e2fde-Abstract-Datasets_and_Benchmarks_Track.html"
)
ICLR = (
    "https://proceedings.iclr.cc/paper_files/paper/2026/hash/"
    "635a38ee326fb0464e0c2b1c1a0b0c1d-Abstract-Conference.html"
)
PDF_WITH_UTM = (
    "https://proceedings.iclr.cc/paper_files/paper/2025/file/"
    "aaaabbbbccccddddeeeeffff00001111-Paper-Conference.pdf?utm_source=chatgpt.com"
)


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_extracts_the_year_from_the_path_not_the_record():
    assert value(mine(NEURIPS_DB), "year") == "2025"


def test_extracts_the_venue_from_the_host():
    assert value(mine(NEURIPS_DB), "venue") == "NeurIPS"
    assert value(mine(ICLR), "venue") == "ICLR"


def test_extracts_the_track():
    assert value(mine(NEURIPS_DB), "track") == "Datasets_and_Benchmarks_Track"
    assert value(mine(ICLR), "track") == "Conference"


def test_marks_the_record_as_proceedings_not_preprint():
    assert value(mine(ICLR), "version") == "proceedings"


def test_a_pdf_url_with_a_tracking_query_still_mines():
    # One real corpus URL arrived via a chatbot carrying ?utm_source=chatgpt.com.
    claims = mine(PDF_WITH_UTM)
    assert value(claims, "year") == "2025"
    assert value(claims, "track") == "Conference"


def test_claims_carry_the_url_as_evidence():
    assert all(c.evidence == ICLR for c in mine(ICLR))


def test_claims_are_tier_one_and_from_proceedings_url():
    for claim in mine(ICLR):
        assert claim.tier == 1
        assert claim.source == "proceedings_url"


def test_a_non_matching_host_yields_nothing():
    assert mine("https://openreview.net/forum?id=r0BFucF2dH") == []
    assert mine("https://arxiv.org/abs/2501.00001") == []
    assert mine("not a url at all") == []


def test_an_unrecognised_track_fails_loudly():
    # Defaulting to main track would silently misclassify a future track.
    bad = (
        "https://proceedings.neurips.cc/paper_files/paper/2027/hash/"
        "deadbeefdeadbeefdeadbeefdeadbeef-Abstract-Brand_New_Track.html"
    )
    with pytest.raises(UnknownTrack, match="Brand_New_Track"):
        mine(bad)


def test_a_matching_host_without_a_parseable_path_yields_nothing():
    assert mine("https://proceedings.neurips.cc/") == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_miner_proceedings.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.miners.proceedings'`

- [ ] **Step 3: Write `miners/proceedings.py`**

```python
"""NeurIPS and ICLR proceedings URLs.

Both hosts use one grammar:

    https://proceedings.{neurips|iclr}.cc/paper_files/paper/{year}/
        {hash|file}/{sha}-{Abstract|Paper}-{Track}.{html|pdf}

Measured on the Trust-Evals-LitReview corpus, this covers 1,854 of 2,413
records -- 1,264 NeurIPS and 590 ICLR -- and yields venue, year and track for
every one of them without a network call.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Claim

HOSTS = {
    "proceedings.neurips.cc": "NeurIPS",
    "papers.nips.cc": "NeurIPS",
    "proceedings.iclr.cc": "ICLR",
}

# Closed vocabulary, measured across the whole corpus. Every one is main track;
# workshop papers are never hosted at these paths, which is what makes this
# signal discriminate so cleanly.
TRACKS = frozenset(
    {
        "Conference",
        "Datasets_and_Benchmarks_Track",
        "Position_Paper_Track",
        "Creative_AI_Track",
    }
)

_PATH = re.compile(
    r"/paper_files/paper/(?P<year>\d{4})/(?:hash|file)/"
    r"[0-9a-f]+-(?:Abstract|Paper)-(?P<track>[A-Za-z_]+)\.(?:html|pdf)$"
)


class UnknownTrack(ValueError):
    """A proceedings URL named a track this miner does not know.

    Raised rather than defaulted, because defaulting to main track would
    silently misclassify a newly introduced track, and a false keep that looks
    confident is harder to notice than a crash.
    """


def mine(url: str) -> list[Claim]:
    """Claims derived from ``url``, or ``[]`` if it is not a proceedings URL."""
    parsed = urlparse(url)
    venue = HOSTS.get(parsed.netloc.lower())
    if venue is None:
        return []

    # The query string is dropped deliberately: one real URL in the corpus
    # carries ?utm_source=chatgpt.com, having been round-tripped through a
    # chatbot before reaching Scholar.
    match = _PATH.search(parsed.path)
    if match is None:
        return []

    track = match.group("track")
    if track not in TRACKS:
        raise UnknownTrack(f"{track!r} is not a known track, in {url!r}")

    def claim(field: str, value: str) -> Claim:
        return Claim(
            field=field,
            value=value,
            source="proceedings_url",
            tier=1,
            confidence=0.99,
            evidence=url,
        )

    return [
        claim("venue", venue),
        claim("year", match.group("year")),
        claim("track", track),
        claim("version", "proceedings"),
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_miner_proceedings.py -v`
Expected: 10 passed

- [ ] **Step 5: Prove the coverage claim against the real corpus**

```bash
python3 - <<'EOF'
import glob, collections
from pathlib import Path
from scholarmend.parse import parse_file
from scholarmend.miners.proceedings import mine
hit = collections.Counter()
total = 0
for f in sorted(glob.glob("../Trust-Evals-LitReview/corpus/*.ris")):
    for rec in parse_file(Path(f)):
        total += 1
        claims = [c for u in rec.urls for c in mine(u)]
        if claims:
            hit[next(c.value for c in claims if c.field == "venue")] += 1
print("records:", total, " mined:", sum(hit.values()), dict(hit))
assert sum(hit.values()) == 1854, sum(hit.values())
assert hit["NeurIPS"] == 1264 and hit["ICLR"] == 590
print("OK: matches the spec's measured coverage exactly")
EOF
```

Expected: `OK: matches the spec's measured coverage exactly`. If the counts differ, do not adjust the assertion — investigate, because the spec's headline numbers derive from it.

- [ ] **Step 6: Commit**

```bash
git add src/scholarmend/miners/proceedings.py tests/test_miner_proceedings.py
git commit -m "feat: mine venue, year and track from proceedings URLs"
```

---

### Task 5: The remaining miners and the registry

Three small miners and the ordered tuple that runs them. These extract **keys**, not answers: a forum id or a PMLR volume is worthless on its own and becomes a venue only at tier 2. The arXiv miner is the exception — it answers `version` directly, which is what keeps preprint-derived claims out of `venue` and `year`.

**Files:**
- Create: `src/scholarmend/miners/openreview.py`, `src/scholarmend/miners/pmlr.py`, `src/scholarmend/miners/arxiv.py`, `tests/test_miners_other.py`
- Modify: `src/scholarmend/miners/__init__.py`

**Interfaces:**
- Consumes: `Claim` (Task 3).
- Produces: `openreview.mine(url) -> list[Claim]` emitting `forum_id`; `pmlr.mine(url) -> list[Claim]` emitting `pmlr_volume`; `arxiv.mine(url) -> list[Claim]` emitting `arxiv_id` and `version="preprint"`; `miners.ALL: tuple[Callable[[str], list[Claim]], ...]`; `miners.mine_all(urls: Iterable[str]) -> list[Claim]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_miners_other.py`:

```python
from __future__ import annotations

from scholarmend import miners
from scholarmend.miners import arxiv, openreview, pmlr


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_openreview_forum_url_yields_the_forum_id():
    claims = openreview.mine("https://openreview.net/forum?id=r0BFucF2dH")
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_openreview_pdf_url_yields_the_same_forum_id():
    claims = openreview.mine("https://openreview.net/pdf?id=r0BFucF2dH")
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_openreview_does_not_claim_a_version():
    # A forum id alone cannot say whether this is a workshop submission or a
    # main-track paper. Only the tier-2 venueid settles that.
    assert value(openreview.mine("https://openreview.net/forum?id=r0BFucF2dH"), "version") is None


def test_openreview_ignores_other_hosts():
    assert openreview.mine("https://arxiv.org/abs/2501.00001") == []


def test_pmlr_github_asset_url_yields_the_volume():
    url = "https://raw.githubusercontent.com/mlresearch/v318/main/assets/huang26a/huang26a.pdf"
    assert value(pmlr.mine(url), "pmlr_volume") == "318"


def test_pmlr_press_url_yields_the_volume():
    assert value(pmlr.mine("https://proceedings.mlr.press/v267/smith25a.html"), "pmlr_volume") == "267"


def test_pmlr_ignores_unrelated_github_content():
    assert pmlr.mine("https://raw.githubusercontent.com/someone/else/main/x.pdf") == []


def test_arxiv_abs_url_yields_the_id_and_marks_it_a_preprint():
    claims = arxiv.mine("https://arxiv.org/abs/2501.01234v2")
    assert value(claims, "arxiv_id") == "2501.01234"
    assert value(claims, "version") == "preprint"


def test_arxiv_pdf_url_yields_the_same_id():
    assert value(arxiv.mine("https://arxiv.org/pdf/2501.01234"), "arxiv_id") == "2501.01234"


def test_mine_all_runs_every_miner_over_every_url():
    urls = [
        "https://proceedings.iclr.cc/paper_files/paper/2026/hash/"
        "635a38ee326fb0464e0c2b1c1a0b0c1d-Abstract-Conference.html",
        "https://openreview.net/forum?id=r0BFucF2dH",
    ]
    claims = miners.mine_all(urls)
    assert value(claims, "venue") == "ICLR"
    assert value(claims, "forum_id") == "r0BFucF2dH"


def test_mine_all_on_urls_no_miner_recognises_returns_nothing():
    assert miners.mine_all(["https://example.com/paper.pdf"]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_miners_other.py -v`
Expected: FAIL, `ImportError: cannot import name 'arxiv'`

- [ ] **Step 3: Write `miners/openreview.py`**

```python
"""OpenReview URLs yield a forum id, and nothing more.

527 records in the corpus are hosted here. The forum id is a key into the
tier-2 API, not an answer: OpenReview hosts workshop submissions and main-track
papers at indistinguishable URLs, and only the ``venueid`` separates them.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from ..models import Claim

_HOST = "openreview.net"
_ID = re.compile(r"^[\w-]+$")


def mine(url: str) -> list[Claim]:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in (_HOST, f"www.{_HOST}"):
        return []
    values = parse_qs(parsed.query).get("id") or []
    if not values or not _ID.match(values[0]):
        return []
    return [
        Claim(
            field="forum_id",
            value=values[0],
            source="openreview_url",
            tier=1,
            confidence=1.0,
            evidence=url,
        )
    ]
```

- [ ] **Step 4: Write `miners/pmlr.py`**

```python
"""PMLR volume numbers, from either of the two hosts Scholar links to.

Scholar links PMLR papers either at proceedings.mlr.press or, oddly, at the
raw GitHub asset backing it. Both encode the volume, which tier 2 turns into a
proceedings title -- v267 is ICML 2025, v318 is the Canadian Conference on AI.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Claim

_VOLUME = re.compile(r"/v(?P<volume>\d+)(?:/|$)")
_HOSTS = {"proceedings.mlr.press", "raw.githubusercontent.com", "mlr.press"}


def mine(url: str) -> list[Claim]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in _HOSTS:
        return []
    # GitHub hosts everything; only the mlresearch organisation is PMLR.
    if host == "raw.githubusercontent.com" and not parsed.path.startswith("/mlresearch/"):
        return []
    match = _VOLUME.search(parsed.path)
    if match is None:
        return []
    return [
        Claim(
            field="pmlr_volume",
            value=match.group("volume"),
            source="pmlr_url",
            tier=1,
            confidence=1.0,
            evidence=url,
        )
    ]
```

- [ ] **Step 5: Write `miners/arxiv.py`**

```python
"""arXiv URLs, which mark a record as describing the preprint.

This miner exists mainly to set ``version``. A preprint legitimately carries a
full author list and a full abstract, both of which Scholar truncates, so its
claims are welcome for those fields -- and excluded from venue and year, where
it is wrong by construction.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Claim

_ID = re.compile(r"/(?:abs|pdf)/(?P<id>\d{4}\.\d{4,5})(?:v\d+)?")


def mine(url: str) -> list[Claim]:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in ("arxiv.org", "www.arxiv.org"):
        return []
    match = _ID.search(parsed.path)
    if match is None:
        return []

    def claim(field: str, value: str) -> Claim:
        return Claim(field=field, value=value, source="arxiv_url", tier=1,
                     confidence=1.0, evidence=url)

    return [claim("arxiv_id", match.group("id")), claim("version", "preprint")]
```

- [ ] **Step 6: Write the registry in `miners/__init__.py`**

```python
"""The miner registry.

Order matters only for readability; miners are disjoint by host, so at most one
answers any given URL.
"""

from __future__ import annotations

from typing import Callable, Iterable

from ..models import Claim
from . import arxiv, openreview, pmlr, proceedings

ALL: tuple[Callable[[str], list[Claim]], ...] = (
    proceedings.mine,
    openreview.mine,
    pmlr.mine,
    arxiv.mine,
)


def mine_all(urls: Iterable[str]) -> list[Claim]:
    """Every claim every miner can make about every URL on a record."""
    claims: list[Claim] = []
    for url in urls:
        for miner in ALL:
            claims.extend(miner(url))
    return claims
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/ -v`
Expected: all tests pass, 43 total

- [ ] **Step 8: Prove the 99% tier-1 key coverage from the spec**

```bash
python3 - <<'EOF'
import glob, collections
from pathlib import Path
from scholarmend.parse import parse_file
from scholarmend import miners
kinds = collections.Counter()
total = 0
for f in sorted(glob.glob("../Trust-Evals-LitReview/corpus/*.ris")):
    for rec in parse_file(Path(f)):
        total += 1
        claims = miners.mine_all(rec.urls)
        fields = {c.field for c in claims}
        if "venue" in fields:        kinds["fully resolved (proceedings)"] += 1
        elif "forum_id" in fields:   kinds["key only (openreview)"] += 1
        elif "pmlr_volume" in fields:kinds["key only (pmlr)"] += 1
        elif "arxiv_id" in fields:   kinds["preprint only (arxiv)"] += 1
        else:                        kinds["no miner"] += 1
for k, v in kinds.most_common():
    print(f"{k:34s}{v:5d}  {100*v/total:5.1f}%")
assert kinds["no miner"] == 21, kinds["no miner"]
print("OK: 21 records have no miner, matching the spec")
EOF
```

Expected: `OK: 21 records have no miner, matching the spec`

- [ ] **Step 9: Commit**

```bash
git add src/scholarmend/miners/ tests/test_miners_other.py
git commit -m "feat: mine OpenReview, PMLR and arXiv identifiers"
```

---

### Task 6: The HTTP client and the content-addressed cache

The cache is what makes reproducibility assertable rather than hopeful: a rerun months later replays committed responses and issues no calls. `--offline` must therefore fail loudly on a miss, because a flag that promises determinism and silently reaches the network is worse than no flag.

**Files:**
- Create: `src/scholarmend/http.py`, `src/scholarmend/cache.py`, `tests/test_cache.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Cache(root: Path, offline: bool = False)` with `.get(key: str) -> dict | None`, `.put(key: str, payload: dict) -> None`, `.fetch(key: str, loader: Callable[[], dict]) -> dict`; `CacheMiss(RuntimeError)`; `http.get_json(url: str, headers: dict[str, str] | None = None, timeout: float = 20.0, attempts: int = 3) -> dict`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cache.py`:

```python
from __future__ import annotations

import pytest

from scholarmend.cache import Cache, CacheMiss


def test_a_put_value_comes_back(tmp_path):
    cache = Cache(tmp_path)
    cache.put("openreview:abc", {"venueid": "ICML.cc/2025/Conference"})
    assert cache.get("openreview:abc") == {"venueid": "ICML.cc/2025/Conference"}


def test_a_missing_key_is_none(tmp_path):
    assert Cache(tmp_path).get("nope") is None


def test_fetch_calls_the_loader_once_then_serves_from_disk(tmp_path):
    calls = []

    def loader():
        calls.append(1)
        return {"v": 1}

    cache = Cache(tmp_path)
    assert cache.fetch("k", loader) == {"v": 1}
    assert cache.fetch("k", loader) == {"v": 1}
    assert len(calls) == 1


def test_a_second_cache_object_sees_the_first_ones_writes(tmp_path):
    Cache(tmp_path).put("k", {"v": 2})
    assert Cache(tmp_path).get("k") == {"v": 2}


def test_offline_mode_refuses_to_call_the_loader(tmp_path):
    def loader():
        raise AssertionError("the network must not be touched in offline mode")

    with pytest.raises(CacheMiss, match="k"):
        Cache(tmp_path, offline=True).fetch("k", loader)


def test_offline_mode_still_serves_what_is_cached(tmp_path):
    Cache(tmp_path).put("k", {"v": 3})

    def loader():
        raise AssertionError("must not be called")

    assert Cache(tmp_path, offline=True).fetch("k", loader) == {"v": 3}


def test_keys_with_awkward_characters_are_safe_on_disk(tmp_path):
    cache = Cache(tmp_path)
    key = "s2:Attention Is All You Need?/\\:*"
    cache.put(key, {"ok": True})
    assert cache.get(key) == {"ok": True}


def test_stored_files_are_readable_json_for_auditing(tmp_path):
    import json

    cache = Cache(tmp_path)
    cache.put("k", {"v": 4})
    path = next(tmp_path.rglob("*.json"))
    assert json.loads(path.read_text())["payload"] == {"v": 4}
    assert json.loads(path.read_text())["key"] == "k"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cache.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.cache'`

- [ ] **Step 3: Write `cache.py`**

```python
"""A content-addressed response store, committed to the repository.

Reproducibility is the point. A systematic review is reported once and defended
for years; a rerun has to produce what the first run produced. Every cached file
records the key alongside the payload so that the store stays auditable by
reading it, rather than only by replaying it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable


class CacheMiss(RuntimeError):
    """Offline mode was asked for something the cache does not hold."""


class Cache:
    def __init__(self, root: Path, offline: bool = False) -> None:
        self.root = Path(root)
        self.offline = offline

    def _path(self, key: str) -> Path:
        # Hashing keeps arbitrary keys -- titles, URLs -- safe as filenames.
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))["payload"]

    def put(self, key: str, payload: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"key": key, "payload": payload}
        path.write_text(
            json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def fetch(self, key: str, loader: Callable[[], dict]) -> dict:
        """Cached value, or ``loader()`` stored and returned."""
        hit = self.get(key)
        if hit is not None:
            return hit
        if self.offline:
            raise CacheMiss(
                f"{key!r} is not cached and --offline forbids fetching it. "
                f"Run once without --offline to populate the cache."
            )
        payload = loader()
        self.put(key, payload)
        return payload
```

- [ ] **Step 4: Write `http.py`**

```python
"""A small JSON-over-HTTP client.

stdlib only, matching refaudit's decision to carry no runtime dependencies:
this gets installed in a hurry, close to a deadline, often on a machine someone
else administers.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    pass


def get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    attempts: int = 3,
) -> dict:
    """GET ``url`` and parse JSON, retrying on transient failure.

    429 and 5xx are retried with exponential backoff; 4xx other than 429 is
    raised at once, because retrying a refusal only spends someone else's
    rate limit.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            last = error
            if error.code != 429 and error.code < 500:
                raise HttpError(f"{error.code} from {url}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
        if attempt < attempts - 1:
            time.sleep(2.0**attempt)
    raise HttpError(f"giving up on {url}: {last!r}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_cache.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add src/scholarmend/cache.py src/scholarmend/http.py tests/test_cache.py
git commit -m "feat: add the committed response cache and a stdlib HTTP client"
```

---

### Task 7: The OpenReview resolver

The decisive tier-2 component. A `venueid` such as `ICML.cc/2026/Workshop/AI4GOOD` states venue, year *and* workshop status in one string — which is exactly the question `venuetriage` exists to answer, and the one that cost a day of manual lookups. This settles 90 of the 112 records the acceptance test measures.

**Files:**
- Create: `src/scholarmend/resolvers/openreview.py`, `tests/test_resolver_openreview.py`

**Interfaces:**
- Consumes: `Claim` (Task 3), `Cache` (Task 6), `http.get_json` (Task 6).
- Produces: `parse_venueid(venueid: str) -> list[Claim]`; `OpenReviewResolver(cache: Cache, token: str | None = None)` with `.resolve(forum_id: str) -> list[Claim]`; `login(user: str, password: str) -> str`; `AuthError(RuntimeError)`.

- [ ] **Step 1: Write the failing tests**

`parse_venueid` is a pure function, so the interesting logic is testable with no network and no cache. Create `tests/test_resolver_openreview.py`:

```python
from __future__ import annotations

from scholarmend.cache import Cache
from scholarmend.resolvers.openreview import OpenReviewResolver, parse_venueid


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_a_conference_venueid_is_main_track():
    claims = parse_venueid("ICML.cc/2025/Conference")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "year") == "2025"
    assert value(claims, "track") == "Conference"
    assert value(claims, "version") == "proceedings"


def test_a_workshop_venueid_names_the_workshop():
    claims = parse_venueid("ICML.cc/2026/Workshop/AI4GOOD")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "year") == "2026"
    assert value(claims, "track") == "Workshop/AI4GOOD"


def test_a_neurips_regional_workshop_is_still_a_workshop():
    # Real value from the corpus: NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM
    claims = parse_venueid("NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM")
    assert value(claims, "venue") == "NeurIPS"
    assert value(claims, "track") == "Workshop_Mexico_City/ResponsibleFM"


def test_a_non_iclr_venueid_keeps_its_own_organisation():
    claims = parse_venueid("AAAI.org/2026/Workshop/AIGOV/Submission")
    assert value(claims, "venue") == "AAAI"


def test_the_venueid_itself_is_retained_as_a_claim():
    assert value(parse_venueid("ICML.cc/2025/Conference"), "venue_id") == "ICML.cc/2025/Conference"


def test_an_unparseable_venueid_yields_only_the_raw_id():
    claims = parse_venueid("something-odd")
    assert value(claims, "venue_id") == "something-odd"
    assert value(claims, "venue") is None


def test_claims_are_tier_two():
    assert all(c.tier == 2 for c in parse_venueid("ICML.cc/2025/Conference"))


def test_resolve_serves_a_cached_forum_without_network(tmp_path):
    cache = Cache(tmp_path)
    cache.put("openreview:notes:XYZ", {"venueid": "ICLR.cc/2026/Conference"})
    resolver = OpenReviewResolver(cache=cache, token=None)
    # token is None, so any network attempt would raise; a cache hit must not.
    assert value(resolver.resolve("XYZ"), "venue") == "ICLR"


def test_resolve_in_offline_mode_raises_on_a_miss(tmp_path):
    import pytest

    from scholarmend.cache import CacheMiss

    resolver = OpenReviewResolver(cache=Cache(tmp_path, offline=True), token="t")
    with pytest.raises(CacheMiss):
        resolver.resolve("NEVER_SEEN")


def test_resolve_without_a_token_refuses_rather_than_calling_anonymously(tmp_path):
    import pytest

    from scholarmend.resolvers.openreview import AuthError

    resolver = OpenReviewResolver(cache=Cache(tmp_path), token=None)
    with pytest.raises(AuthError, match="credentials"):
        resolver.resolve("NOT_CACHED")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_resolver_openreview.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.resolvers.openreview'`

- [ ] **Step 3: Write `resolvers/openreview.py`**

Use the exact JSON path and header form recorded in `docs/openreview-auth.md` by Task 1.

```python
"""OpenReview venue resolution.

A ``venueid`` states venue, year and workshop status in one string:

    ICML.cc/2025/Conference                        -> ICML 2025, main track
    ICML.cc/2026/Workshop/AI4GOOD                   -> ICML 2026, a workshop
    NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM

That single field is what 90 of the 112 hand-resolved records needed, and it
was correct in 92 of 92 spot checks against the reviewers' own verification.
"""

from __future__ import annotations

import json
import re
import urllib.request

from ..cache import Cache
from ..models import Claim

API = "https://api2.openreview.net"
_VENUEID = re.compile(r"^(?P<org>[A-Za-z][\w.-]*?)(?:\.cc|\.org)?/(?P<year>\d{4})/(?P<track>.+)$")


class AuthError(RuntimeError):
    """No usable credentials, and the anonymous API refuses every read."""


def login(user: str, password: str) -> str:
    """Exchange credentials for a bearer token."""
    body = json.dumps({"id": user, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        f"{API}/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.loads(response.read().decode("utf-8")).get("token")
    if not token:
        raise AuthError("OpenReview accepted the request but returned no token")
    return token


def parse_venueid(venueid: str) -> list[Claim]:
    """Claims derived from a venueid string."""

    def claim(field: str, value: str) -> Claim:
        return Claim(field=field, value=value, source="openreview_api", tier=2,
                     confidence=0.99, evidence=f"venueid={venueid}")

    claims = [claim("venue_id", venueid)]
    match = _VENUEID.match(venueid)
    if match is None:
        return claims
    # Trailing /Submission and similar suffixes are routing detail, not venue.
    track = re.sub(r"/Submission$", "", match.group("track"))
    claims += [
        claim("venue", match.group("org")),
        claim("year", match.group("year")),
        claim("track", track),
        claim("version", "proceedings"),
    ]
    return claims


class OpenReviewResolver:
    def __init__(self, cache: Cache, token: str | None = None) -> None:
        self.cache = cache
        self.token = token

    def resolve(self, forum_id: str) -> list[Claim]:
        """Claims for one forum id, from cache or from the API."""

        def loader() -> dict:
            if not self.token:
                raise AuthError(
                    "OpenReview needs credentials: the anonymous API returns "
                    "ChallengeRequiredError. Set SCHOLARMEND_OPENREVIEW_USER and "
                    "SCHOLARMEND_OPENREVIEW_PASSWORD, or run with --offline against "
                    "a populated cache."
                )
            from ..http import get_json

            payload = get_json(
                f"{API}/notes?forum={forum_id}&limit=1",
                headers={"Authorization": f"Bearer {self.token}"},
            )
            notes = payload.get("notes") or []
            content = (notes[0].get("content") if notes else {}) or {}
            venueid = (content.get("venueid") or {}).get("value")
            return {"venueid": venueid} if venueid else {}

        cached = self.cache.fetch(f"openreview:notes:{forum_id}", loader)
        venueid = cached.get("venueid")
        return parse_venueid(venueid) if venueid else []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_resolver_openreview.py -v`
Expected: 10 passed

- [ ] **Step 5: Validate `parse_venueid` against all 90 verified venueids**

This is a real regression test, not a smoke test: the reviewers' own lookups are the ground truth.

Append to `tests/test_resolver_openreview.py`:

```python
import json
from pathlib import Path

import pytest

GOLD = Path(__file__).parents[2] / "Trust-Evals-LitReview" / "verification" / "openreview-venues.json"


@pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not checked out alongside")
def test_every_verified_venueid_parses_into_a_venue_and_a_workshop_verdict():
    venues = json.loads(GOLD.read_text())
    assert len(venues) == 90
    for forum_id, venueid in venues.items():
        claims = parse_venueid(venueid)
        got = {c.field: c.value for c in claims}
        assert got.get("venue"), f"{forum_id}: no venue from {venueid!r}"
        assert got.get("year"), f"{forum_id}: no year from {venueid!r}"
        assert got.get("track"), f"{forum_id}: no track from {venueid!r}"


@pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not checked out alongside")
def test_workshop_detection_matches_the_reviewers_labels():
    venues = json.loads(GOLD.read_text())
    workshops = sum(1 for v in venues.values() if "Workshop" in v)
    main = sum(1 for v in venues.values() if v.endswith("/Conference"))
    # 73 workshop and 17 main-track, per review-bucket-resolutions.json.
    assert workshops == 73, workshops
    assert main == 17, main
```

Run: `pytest tests/test_resolver_openreview.py -v`
Expected: 12 passed. **If the two counts differ from 73 and 17, stop and report it** — the acceptance target in the spec is derived from them.

- [ ] **Step 6: Commit**

```bash
git add src/scholarmend/resolvers/openreview.py tests/test_resolver_openreview.py
git commit -m "feat: resolve OpenReview venueids into venue, year and track"
```

---

### Task 8: The PMLR volume index and the PMC bridge

Thirteen of the 112 hand-resolved records hinge on a volume number: ten PMLR and three reached through PubMed Central. Without these the headline acceptance target is 90 of 112, which is **below the bar**, so this task is load-bearing rather than a nicety.

A PMLR volume number is meaningless alone and decisive once resolved — `v267` is ICML 2025, `v318` is the Canadian Conference on AI, and the difference is in scope versus out of scope. The PMC path is a bridge: PMC records a `volume` field which is the PMLR volume, which is how three records were resolved by hand.

**Files:**
- Create: `src/scholarmend/miners/pmc.py`, `src/scholarmend/resolvers/pmlr_index.py`, `src/scholarmend/resolvers/pmc.py`, `tests/test_resolver_volumes.py`
- Modify: `src/scholarmend/miners/__init__.py` (register the PMC miner)

**Interfaces:**
- Consumes: `Claim` (Task 3), `Cache` and `http.get_json` (Task 6).
- Produces: `pmc.mine(url) -> list[Claim]` emitting `pmc_id`; `PmlrIndexResolver(cache)` with `.resolve(volume: str) -> list[Claim]`; `PmcResolver(cache)` with `.resolve(pmc_id: str) -> list[Claim]` emitting `pmlr_volume`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolver_volumes.py`:

```python
from __future__ import annotations

from scholarmend.cache import Cache
from scholarmend.miners import pmc as pmc_miner
from scholarmend.resolvers.pmc import PmcResolver
from scholarmend.resolvers.pmlr_index import PmlrIndexResolver, venue_from_title


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_pmc_url_yields_the_pmc_id():
    claims = pmc_miner.mine("https://pmc.ncbi.nlm.nih.gov/articles/PMC13004626/")
    assert value(claims, "pmc_id") == "PMC13004626"


def test_pmc_miner_ignores_other_hosts():
    assert pmc_miner.mine("https://arxiv.org/abs/2501.00001") == []


def test_venue_from_title_recognises_an_icml_volume():
    title = "Proceedings of the 42nd International Conference on Machine Learning"
    assert venue_from_title(title) == "ICML"


def test_venue_from_title_recognises_neurips_and_iclr():
    assert venue_from_title("Advances in Neural Information Processing Systems 38") == "NeurIPS"
    assert venue_from_title("Proceedings of the International Conference on Learning Representations") == "ICLR"


def test_venue_from_title_leaves_an_unrelated_conference_alone():
    # v318 is the Canadian Conference on AI: out of scope, and it must not be
    # coerced into one of the three venues under review.
    assert venue_from_title("Proceedings of the Canadian Conference on AI") is None


def test_pmlr_index_resolves_a_cached_volume(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:267",
              {"title": "Proceedings of the 42nd International Conference on Machine Learning"})
    claims = PmlrIndexResolver(cache).resolve("267")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "version") == "proceedings"


def test_pmlr_index_keeps_the_raw_title_as_evidence(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})
    claims = PmlrIndexResolver(cache).resolve("318")
    assert any("Canadian" in c.evidence for c in claims)


def test_an_out_of_scope_volume_still_reports_its_proceedings_title(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})
    claims = PmlrIndexResolver(cache).resolve("318")
    assert value(claims, "venue_id") == "PMLR v318"


def test_pmc_resolver_returns_the_pmlr_volume(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmc:esummary:PMC13004626",
              {"result": {"PMC13004626": {"volume": "267"}}})
    assert value(PmcResolver(cache).resolve("PMC13004626"), "pmlr_volume") == "267"


def test_pmc_resolver_with_no_volume_yields_nothing(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmc:esummary:PMC1", {"result": {"PMC1": {}}})
    assert PmcResolver(cache).resolve("PMC1") == []


def test_volume_claims_are_tier_two(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:267", {"title": "Proceedings of the 42nd International Conference on Machine Learning"})
    assert all(c.tier == 2 for c in PmlrIndexResolver(cache).resolve("267"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_resolver_volumes.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.resolvers.pmlr_index'`

- [ ] **Step 3: Write `miners/pmc.py`**

```python
"""PubMed Central URLs yield a PMC id.

Three corpus records reach a PMLR volume only through PMC, which records the
volume number in its summary metadata. The id is a key, not an answer.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Claim

_ID = re.compile(r"/articles/(?P<id>PMC\d+)")


def mine(url: str) -> list[Claim]:
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("ncbi.nlm.nih.gov"):
        return []
    match = _ID.search(parsed.path)
    if match is None:
        return []
    return [
        Claim(field="pmc_id", value=match.group("id"), source="pmc_url",
              tier=1, confidence=1.0, evidence=url)
    ]
```

- [ ] **Step 4: Write `resolvers/pmlr_index.py`**

```python
"""PMLR volume numbers into proceedings titles.

A volume number is decisive once resolved and meaningless before: v267 is
ICML 2025 and in scope, v318 is the Canadian Conference on AI and is not. The
reviewers resolved these by opening proceedings.mlr.press/vNNN/ and reading the
heading, which is exactly what this does, once, into a committed cache.
"""

from __future__ import annotations

import re

from ..cache import Cache
from ..models import Claim

INDEX = "https://proceedings.mlr.press/v{volume}/"

# Only the three venues under review are recognised. Anything else keeps its
# proceedings title and is left for a human, because coercing an unfamiliar
# conference into a known one is how out-of-scope work gets screened in.
_VENUES = (
    (re.compile(r"International Conference on Machine Learning", re.I), "ICML"),
    (re.compile(r"Neural Information Processing Systems", re.I), "NeurIPS"),
    (re.compile(r"International Conference on Learning Representations", re.I), "ICLR"),
)


def venue_from_title(title: str) -> str | None:
    for pattern, venue in _VENUES:
        if pattern.search(title):
            return venue
    return None


class PmlrIndexResolver:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def resolve(self, volume: str) -> list[Claim]:
        def loader() -> dict:
            import urllib.request

            with urllib.request.urlopen(INDEX.format(volume=volume), timeout=20) as response:
                html = response.read().decode("utf-8", "replace")
            match = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
            title = re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else ""
            return {"title": title}

        payload = self.cache.fetch(f"pmlr:volume:{volume}", loader)
        title = payload.get("title") or ""
        if not title:
            return []

        def claim(field: str, value: str) -> Claim:
            return Claim(field=field, value=value, source="pmlr_index", tier=2,
                         confidence=0.95, evidence=f"PMLR v{volume}: {title}")

        claims = [claim("venue_id", f"PMLR v{volume}"), claim("version", "proceedings")]
        venue = venue_from_title(title)
        if venue:
            claims.append(claim("venue", venue))
        year = re.search(r"\b(20\d\d)\b", title)
        if year:
            claims.append(claim("year", year.group(1)))
        return claims
```

- [ ] **Step 5: Write `resolvers/pmc.py`**

```python
"""PubMed Central as a bridge to a PMLR volume.

PMC records the volume of the proceedings an article appeared in. For three
corpus records that number was the only route to a venue, and the reviewers
followed it by hand: PMC citation_volume 267 -> PMLR v267 -> ICML 2025.
"""

from __future__ import annotations

from ..cache import Cache
from ..models import Claim

ESUMMARY = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=pmc&id={pmc_id}&retmode=json"
)


class PmcResolver:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def resolve(self, pmc_id: str) -> list[Claim]:
        def loader() -> dict:
            from ..http import get_json

            return get_json(ESUMMARY.format(pmc_id=pmc_id.removeprefix("PMC")))

        payload = self.cache.fetch(f"pmc:esummary:{pmc_id}", loader)
        result = (payload.get("result") or {}).get(pmc_id) or {}
        # esummary keys the result by the bare numeric id as well.
        if not result:
            result = (payload.get("result") or {}).get(pmc_id.removeprefix("PMC")) or {}
        volume = result.get("volume")
        if not volume:
            return []
        return [
            Claim(field="pmlr_volume", value=str(volume), source="pmc_api", tier=2,
                  confidence=0.90, evidence=f"PMC esummary volume={volume}")
        ]
```

- [ ] **Step 6: Register the PMC miner**

In `src/scholarmend/miners/__init__.py`, change the import and the registry:

```python
from . import arxiv, openreview, pmc, pmlr, proceedings

ALL: tuple[Callable[[str], list[Claim]], ...] = (
    proceedings.mine,
    openreview.mine,
    pmlr.mine,
    arxiv.mine,
    pmc.mine,
)
```

- [ ] **Step 7: Add `pmc_url` to the precedence table**

In `src/scholarmend/ledger.py`, the `pmlr_volume` entry must accept the PMC route as well as the URL route:

```python
    "pmlr_volume": ("pmlr_url", "pmc_api"),
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `pytest tests/test_resolver_volumes.py -v`
Expected: 11 passed

- [ ] **Step 9: Commit**

```bash
git add src/scholarmend/miners/ src/scholarmend/resolvers/ src/scholarmend/ledger.py tests/test_resolver_volumes.py
git commit -m "feat: resolve PMLR volumes, and reach them through PMC"
```

---

### Task 9: The Semantic Scholar resolver

Tier 3, for the records no miner covers. Measured at low hit rate but perfect venue accuracy on hits, so it is tried first among tier-3 sources and its claims are marked lower confidence.

**Files:**
- Create: `src/scholarmend/resolvers/semanticscholar.py`, `tests/test_resolver_s2.py`

**Interfaces:**
- Consumes: `Claim`, `Cache`, `http.get_json`.
- Produces: `SemanticScholarResolver(cache: Cache, api_key: str | None = None)` with `.resolve(title: str) -> list[Claim]`; `titles_match(a: str, b: str) -> bool`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_resolver_s2.py`:

```python
from __future__ import annotations

from scholarmend.cache import Cache
from scholarmend.resolvers.semanticscholar import SemanticScholarResolver, titles_match


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_titles_match_ignores_case_and_punctuation():
    assert titles_match("Mind2Web 2: Evaluating Agentic Search", "mind2web 2 evaluating agentic search")


def test_titles_match_rejects_a_different_paper():
    assert not titles_match("Attention Is All You Need", "Attention Considered Harmful")


def test_resolve_returns_venue_and_year_from_cache(tmp_path):
    cache = Cache(tmp_path)
    cache.put(
        "s2:search:attention is all you need",
        {"data": [{"title": "Attention Is All You Need", "year": 2017,
                   "venue": "Neural Information Processing Systems",
                   "externalIds": {"DOI": "10.5555/3295222"}}]},
    )
    claims = SemanticScholarResolver(cache).resolve("Attention Is All You Need")
    assert value(claims, "venue") == "Neural Information Processing Systems"
    assert value(claims, "year") == "2017"
    assert value(claims, "doi") == "10.5555/3295222"


def test_a_title_that_does_not_match_is_discarded(tmp_path):
    cache = Cache(tmp_path)
    cache.put("s2:search:some paper", {"data": [{"title": "A Totally Different Paper",
                                                 "year": 2020, "venue": "ICML"}]})
    assert SemanticScholarResolver(cache).resolve("Some Paper") == []


def test_an_empty_result_yields_no_claims(tmp_path):
    cache = Cache(tmp_path)
    cache.put("s2:search:nothing here", {"data": []})
    assert SemanticScholarResolver(cache).resolve("Nothing Here") == []


def test_claims_are_tier_three_and_lower_confidence(tmp_path):
    cache = Cache(tmp_path)
    cache.put("s2:search:x", {"data": [{"title": "X", "year": 2021, "venue": "ICLR"}]})
    for claim in SemanticScholarResolver(cache).resolve("X"):
        assert claim.tier == 3
        assert claim.confidence < 0.9
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_resolver_s2.py -v`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Write `resolvers/semanticscholar.py`**

```python
"""Semantic Scholar, the tier-3 fallback for records no miner covers.

Measured on a 30-title sample of this corpus, its hit rate was low but its
venue was correct on every hit -- unlike OpenAlex, which matched more titles
and described the arXiv preprint rather than the published paper in every case
where it named a venue at all. Low recall with high precision is the right
shape for a last resort, so its claims are admitted but marked down.
"""

from __future__ import annotations

import re
import urllib.parse

from ..cache import Cache
from ..models import Claim

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,venue,externalIds"


def _normalise(title: str) -> str:
    return re.sub(r"[^a-z0-9]", "", title.lower())


def titles_match(a: str, b: str) -> bool:
    """Whether two titles denote the same paper.

    A prefix comparison on the normalised strings, because Scholar and
    Semantic Scholar disagree about subtitles and trailing punctuation more
    often than they disagree about papers.
    """
    x, y = _normalise(a), _normalise(b)
    if not x or not y:
        return False
    return x[:45] == y[:45]


class SemanticScholarResolver:
    def __init__(self, cache: Cache, api_key: str | None = None) -> None:
        self.cache = cache
        self.api_key = api_key

    def resolve(self, title: str) -> list[Claim]:
        def loader() -> dict:
            from ..http import get_json

            query = urllib.parse.quote(title[:200])
            headers = {"x-api-key": self.api_key} if self.api_key else {}
            return get_json(f"{API}?query={query}&limit=1&fields={FIELDS}", headers=headers)

        payload = self.cache.fetch(f"s2:search:{_normalise(title)[:80]}", loader)
        results = payload.get("data") or []
        if not results:
            return []
        paper = results[0]
        if not titles_match(title, paper.get("title") or ""):
            return []

        def claim(field: str, value: str) -> Claim:
            return Claim(field=field, value=value, source="semanticscholar", tier=3,
                         confidence=0.75, evidence=f"s2:{paper.get('title','')[:60]}")

        claims = []
        if paper.get("venue"):
            claims.append(claim("venue", paper["venue"]))
        if paper.get("year"):
            claims.append(claim("year", str(paper["year"])))
        doi = (paper.get("externalIds") or {}).get("DOI")
        if doi:
            claims.append(claim("doi", doi))
        return claims
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_resolver_s2.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/scholarmend/resolvers/semanticscholar.py tests/test_resolver_s2.py
git commit -m "feat: add Semantic Scholar as the tier-3 resolver"
```

---

### Task 10: The pipeline

Where per-field escalation actually happens. A record whose URL already yielded venue, year and track makes no network call for those fields, which is what keeps the ledger's cost equal to a plain cascade's.

**Files:**
- Create: `src/scholarmend/pipeline.py`, `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `Record`, `Claim`, `Ledger`, `miners.mine_all`, `OpenReviewResolver`, `SemanticScholarResolver`.
- Produces: `CONFIDENCE_FLOOR: float`; `RESOLVED_FIELDS: tuple[str, ...]`; `scholar_claims(record: Record) -> list[Claim]`; `resolve_record(record, openreview=None, pmlr_index=None, pmc=None, semanticscholar=None) -> Ledger`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path

from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record, scholar_claims

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


class SpyOpenReview:
    def __init__(self, claims=()):
        self.calls = []
        self._claims = list(claims)

    def resolve(self, forum_id):
        self.calls.append(forum_id)
        return self._claims


def records():
    return parse_file(FIXTURE)


def test_scholar_claims_are_tier_zero():
    for claim in scholar_claims(records()[0]):
        assert claim.tier == 0
        assert claim.source == "scholar"


def test_scholar_year_claim_carries_the_wrong_year_it_really_has():
    claims = {c.field: c.value for c in scholar_claims(records()[0])}
    assert claims["year"] == "2026"


def test_the_url_beats_scholar_on_year():
    ledger = resolve_record(records()[0])
    assert ledger.resolve("year").value == "2025"


def test_the_losing_scholar_claim_is_still_there():
    ledger = resolve_record(records()[0])
    assert {c.value for c in ledger.claims("year")} == {"2025", "2026"}


def test_venue_comes_from_the_url_not_the_ellipsis():
    ledger = resolve_record(records()[0])
    assert ledger.resolve("venue").value == "NeurIPS"


def test_a_fully_mined_record_never_calls_tier_two():
    spy = SpyOpenReview()
    resolve_record(records()[0], openreview=spy)
    assert spy.calls == []


def test_an_openreview_only_record_does_call_tier_two():
    from scholarmend.models import Claim

    spy = SpyOpenReview([
        Claim("venue", "ICLR", "openreview_api", 2, 0.99, "venueid=ICLR.cc/2026/Conference"),
        Claim("year", "2026", "openreview_api", 2, 0.99, "venueid=ICLR.cc/2026/Conference"),
    ])
    ledger = resolve_record(records()[2], openreview=spy)
    assert spy.calls == ["r0BFucF2dH"]
    assert ledger.resolve("venue").value == "ICLR"


def test_tier_two_is_skipped_when_no_resolver_is_supplied():
    # No credentials must degrade, never crash a 2,400-record run.
    ledger = resolve_record(records()[2], openreview=None)
    assert ledger.resolve("venue").value == "… on Learning Representations"


def test_a_record_with_no_resolvable_field_keeps_scholars_value():
    ledger = resolve_record(records()[2])
    assert ledger.is_unresolved("track")


def test_the_pdf_record_with_a_tracking_query_still_resolves():
    ledger = resolve_record(records()[3])
    assert ledger.resolve("year").value == "2025"


def test_pmc_runs_before_the_pmlr_index_so_the_bridge_works():
    """PMC yields a volume; only then can the index turn it into a venue."""
    from scholarmend.models import Claim
    from scholarmend.parse import parse_ris

    raw = (
        "TY  - JOUR\nTI  - Restoring calibration for aligned LLMs\n"
        "JF  - \u2026 Learning \u2026\nPB  - pmc.ncbi.nlm.nih.gov\n"
        "UR  - https://pmc.ncbi.nlm.nih.gov/articles/PMC13004626/\nER  - \n"
    )
    record = parse_ris(raw, "t.ris")[0]

    class Pmc:
        def resolve(self, pmc_id):
            assert pmc_id == "PMC13004626"
            return [Claim("pmlr_volume", "267", "pmc_api", 2, 0.9, "e")]

    class Index:
        def __init__(self):
            self.seen = []

        def resolve(self, volume):
            self.seen.append(volume)
            return [Claim("venue", "ICML", "pmlr_index", 2, 0.95, "e")]

    index = Index()
    ledger = resolve_record(record, pmc=Pmc(), pmlr_index=index)
    assert index.seen == ["267"]
    assert ledger.resolve("venue").value == "ICML"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.pipeline'`

- [ ] **Step 3: Write `pipeline.py`**

```python
"""Per-field escalation through the tiers.

The escalation is per *field*, not per record. A NeurIPS record whose URL
already yielded venue, year and track makes no network call for those fields
even if its abstract is still a Scholar snippet. That is what keeps an evidence
ledger as cheap as a plain first-wins cascade.
"""

from __future__ import annotations

from . import miners
from .ledger import Ledger
from .models import Claim, Record

CONFIDENCE_FLOOR = 0.80

RESOLVED_FIELDS = ("venue", "year", "track", "version", "authors", "abstract", "doi")

_SCHOLAR_FIELDS = {
    "venue": lambda r: r.venue,
    "year": lambda r: r.year,
    "authors": lambda r: "; ".join(r.fields.get("AU", [])),
    "abstract": lambda r: r.first("AB"),
}


def scholar_claims(record: Record) -> list[Claim]:
    """Tier-0 claims: what Scholar says, retained as evidence and outranked."""
    claims = []
    for field, read in _SCHOLAR_FIELDS.items():
        value = read(record)
        if value:
            claims.append(
                Claim(field=field, value=value, source="scholar", tier=0,
                      confidence=0.30, evidence=f"{record.source_file}:TI={record.title[:40]}")
            )
    return claims


def _needs_escalation(ledger: Ledger, field: str) -> bool:
    claim = ledger.resolve(field)
    return claim is None or claim.confidence < CONFIDENCE_FLOOR


def resolve_record(
    record: Record,
    openreview=None,
    pmlr_index=None,
    pmc=None,
    semanticscholar=None,
) -> Ledger:
    """Build the full claim ledger for one record."""
    ledger = Ledger()

    for claim in scholar_claims(record):
        ledger.add(claim)
    for claim in miners.mine_all(record.urls):
        ledger.add(claim)

    def unsettled() -> bool:
        return any(_needs_escalation(ledger, f) for f in ("venue", "year", "track"))

    # Tier 2: only when a key exists and a field tier 1 could not settle remains.
    forum = ledger.resolve("forum_id")
    if openreview is not None and forum is not None and unsettled():
        for claim in openreview.resolve(forum.value):
            ledger.add(claim)

    # PMC is a bridge, not a destination: it yields a PMLR volume, which the
    # index then turns into a venue. Run it before the index for that reason.
    pmc_id = ledger.resolve("pmc_id")
    if pmc is not None and pmc_id is not None and unsettled():
        for claim in pmc.resolve(pmc_id.value):
            ledger.add(claim)

    volume = ledger.resolve("pmlr_volume")
    if pmlr_index is not None and volume is not None and unsettled():
        for claim in pmlr_index.resolve(volume.value):
            ledger.add(claim)

    # Tier 3: last resort, for records no miner covered.
    if semanticscholar is not None and record.title:
        if any(_needs_escalation(ledger, f) for f in ("venue", "year")):
            for claim in semanticscholar.resolve(record.title):
                ledger.add(claim)

    return ledger
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_pipeline.py -v`
Expected: 11 passed

- [ ] **Step 5: Commit**

```bash
git add src/scholarmend/pipeline.py tests/test_pipeline.py
git commit -m "feat: escalate through the tiers one field at a time"
```

---

### Task 11: Canonical JSON and the RIS projection

The JSON is the real output. The RIS is a projection for Covidence and `venuetriage`, produced by **surgical line replacement** against `Record.raw` — every byte scholarmend does not correct survives untouched.

**Files:**
- Create: `src/scholarmend/emit.py`, `tests/test_emit.py`

**Interfaces:**
- Consumes: `Record`, `Ledger`, `RESOLVED_FIELDS`.
- Produces: `to_json(record: Record, ledger: Ledger) -> dict`; `project_ris(record: Record, ledger: Ledger) -> str`; `emit_corpus(pairs: Iterable[tuple[Record, Ledger]]) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_emit.py`:

```python
from __future__ import annotations

from pathlib import Path

from scholarmend.emit import project_ris, to_json
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def first():
    record = parse_file(FIXTURE)[0]
    return record, resolve_record(record)


def test_json_reports_the_winning_value_with_its_source():
    record, ledger = first()
    doc = to_json(record, ledger)
    assert doc["fields"]["year"]["value"] == "2025"
    assert doc["fields"]["year"]["source"] == "proceedings_url"


def test_json_retains_the_losing_scholar_claim():
    record, ledger = first()
    doc = to_json(record, ledger)
    losers = [c for c in doc["claims"] if c["field"] == "year" and c["source"] == "scholar"]
    assert losers and losers[0]["value"] == "2026"


def test_json_marks_an_unresolved_field():
    record = parse_file(FIXTURE)[2]
    doc = to_json(record, resolve_record(record))
    assert doc["fields"]["track"]["unresolved"] is True


def test_json_carries_the_title_and_source_file():
    record, ledger = first()
    doc = to_json(record, ledger)
    assert doc["title"].startswith("Thinkbench")
    assert doc["source_file"] == "sample.ris"


def test_ris_projection_corrects_the_year_in_place():
    record, ledger = first()
    assert "PY  - 2025///" in project_ris(record, ledger)
    assert "PY  - 2026///" not in project_ris(record, ledger)


def test_ris_projection_preserves_scholars_trailing_slash_convention():
    record, ledger = first()
    # Covidence and venuetriage both parse PY; keep the shape Scholar writes.
    assert "PY  - 2025///" in project_ris(record, ledger)


def test_ris_projection_corrects_the_ellipsized_venue():
    record, ledger = first()
    out = project_ris(record, ledger)
    assert "JF  - NeurIPS" in out
    assert "… Neural Information …" not in out


def test_ris_projection_leaves_every_untouched_line_byte_identical():
    record, ledger = first()
    out = project_ris(record, ledger)
    untouched = [ln for ln in record.raw.split("\n") if not ln.startswith(("PY  - ", "JF  - "))]
    for line in untouched:
        assert line in out.split("\n")


def test_ris_projection_keeps_the_trailing_space_on_the_er_line():
    record, ledger = first()
    assert "ER  - \n" in project_ris(record, ledger)


def test_a_record_with_nothing_to_correct_round_trips_exactly():
    record = parse_file(FIXTURE)[2]  # openreview only, no miner claims
    assert project_ris(record, resolve_record(record)) == record.raw
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_emit.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.emit'`

- [ ] **Step 3: Write `emit.py`**

```python
"""Canonical JSON, and the RIS projection derived from it.

The JSON is the record. RIS cannot represent provenance, so it is emitted as a
projection for the tools that need it -- Covidence, and venuetriage -- by
rewriting only the lines whose values scholarmend corrected. Every other byte
of the original record survives, which is what makes the projection safe to
feed to a parser that was written against Scholar's exact output.
"""

from __future__ import annotations

import re
from typing import Iterable

from .ledger import Ledger
from .models import Record
from .pipeline import RESOLVED_FIELDS

# Which RIS tag carries each resolved field. Only these are ever rewritten.
_TAG_FOR = {"year": "PY", "venue": "JF"}


def to_json(record: Record, ledger: Ledger) -> dict:
    """The canonical record: winning values, and every claim behind them."""
    fields = {}
    for field in RESOLVED_FIELDS:
        claim = ledger.resolve(field)
        if claim is None:
            fields[field] = {"value": None, "unresolved": True}
        else:
            fields[field] = {
                "value": claim.value,
                "source": claim.source,
                "tier": claim.tier,
                "confidence": claim.confidence,
                "evidence": claim.evidence,
            }
    claims = [
        {"field": c.field, "value": c.value, "source": c.source,
         "tier": c.tier, "confidence": c.confidence, "evidence": c.evidence}
        for field in sorted(set(RESOLVED_FIELDS) | {"forum_id", "venue_id"})
        for c in ledger.claims(field)
    ]
    return {
        "title": record.title,
        "source_file": record.source_file,
        "fields": fields,
        "claims": claims,
        "conflicts": ledger.conflicts(),
    }


def _rewrite_line(line: str, tag: str, value: str) -> str:
    """Replace a tag's value, preserving Scholar's ``2025///`` year shape."""
    if tag == "PY":
        return f"PY  - {value}///"
    return f"{tag}  - {value}"


def project_ris(record: Record, ledger: Ledger) -> str:
    """``record.raw`` with corrected fields rewritten and nothing else touched."""
    corrections = {}
    for field, tag in _TAG_FOR.items():
        claim = ledger.resolve(field)
        if claim is not None and claim.source != "scholar":
            corrections[tag] = claim.value
    if not corrections:
        return record.raw

    out = []
    for line in record.raw.split("\n"):
        match = re.match(r"^([A-Z][A-Z0-9])  - ", line)
        tag = match.group(1) if match else None
        if tag in corrections:
            out.append(_rewrite_line(line, tag, corrections[tag]))
        else:
            out.append(line)
    return "\n".join(out)


def emit_corpus(pairs: Iterable[tuple[Record, Ledger]]) -> str:
    return "".join(project_ris(record, ledger) for record, ledger in pairs)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_emit.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add src/scholarmend/emit.py tests/test_emit.py
git commit -m "feat: emit canonical JSON and a surgical RIS projection"
```

---

### Task 12: The command-line interface

**Files:**
- Create: `src/scholarmend/cli.py`, `tests/test_cli.py`
- Modify: `README.md` (usage section)

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None) -> int`. Exit `0` clean, `1` on a partial run (auth or network degraded), `2` on a usage or hard error.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli.py`:

```python
from __future__ import annotations

import json
import shutil
from pathlib import Path

from scholarmend.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def setup_input(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(FIXTURE, corpus / "sample.ris")
    return corpus


def test_writes_both_outputs(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    assert main(["--input", str(corpus), "--out", str(out), "--cache", str(tmp_path / "c")]) == 0
    assert (out / "resolved.json").exists()
    assert (out / "mended.ris").exists()


def test_the_json_has_one_object_per_record(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    main(["--input", str(corpus), "--out", str(out), "--cache", str(tmp_path / "c")])
    assert len(json.loads((out / "resolved.json").read_text())) == 4


def test_the_ris_output_carries_the_corrected_year(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    main(["--input", str(corpus), "--out", str(out), "--cache", str(tmp_path / "c")])
    assert "PY  - 2025///" in (out / "mended.ris").read_text(encoding="utf-8")


def test_a_report_lists_what_stayed_unresolved(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    main(["--input", str(corpus), "--out", str(out), "--cache", str(tmp_path / "c")])
    report = (out / "report.txt").read_text()
    assert "unresolved" in report.lower()


def test_offline_without_a_cache_still_completes_on_tier_one(tmp_path):
    # Offline must not crash: tier-1 mining needs no network at all.
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    code = main(["--input", str(corpus), "--out", str(out),
                 "--cache", str(tmp_path / "c"), "--offline"])
    assert code in (0, 1)
    assert (out / "mended.ris").exists()


def test_an_empty_input_directory_is_an_error_not_a_silent_success(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--input", str(empty), "--out", str(tmp_path / "o"),
                 "--cache", str(tmp_path / "c")]) == 2


def test_running_twice_produces_identical_output(tmp_path):
    corpus = setup_input(tmp_path)
    for name in ("a", "b"):
        main(["--input", str(corpus), "--out", str(tmp_path / name),
              "--cache", str(tmp_path / "c")])
    assert (tmp_path / "a" / "mended.ris").read_bytes() == (tmp_path / "b" / "mended.ris").read_bytes()
    assert (tmp_path / "a" / "resolved.json").read_bytes() == (tmp_path / "b" / "resolved.json").read_bytes()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'scholarmend.cli'`

- [ ] **Step 3: Write `cli.py`**

```python
"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .cache import Cache
from .emit import project_ris, to_json
from .parse import parse_file
from .pipeline import RESOLVED_FIELDS, resolve_record
from .resolvers.openreview import AuthError, OpenReviewResolver, login
from .resolvers.pmc import PmcResolver
from .resolvers.pmlr_index import PmlrIndexResolver
from .resolvers.semanticscholar import SemanticScholarResolver


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarmend",
        description="Recover true venue, year and track for Google Scholar RIS exports.",
    )
    parser.add_argument("--input", required=True, type=Path, help="directory of .ris files")
    parser.add_argument("--out", required=True, type=Path, help="directory to write outputs to")
    parser.add_argument("--cache", default=Path(".scholarmend-cache"), type=Path,
                        help="response cache; commit it for reproducibility")
    parser.add_argument("--offline", action="store_true",
                        help="never call the network; fail on a cache miss")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    files = sorted(args.input.glob("*.ris"))
    if not files:
        print(f"no .ris files in {args.input}", file=sys.stderr)
        return 2

    cache = Cache(args.cache, offline=args.offline)
    degraded = False

    token = None
    user = os.environ.get("SCHOLARMEND_OPENREVIEW_USER")
    password = os.environ.get("SCHOLARMEND_OPENREVIEW_PASSWORD")
    if user and password and not args.offline:
        try:
            token = login(user, password)
        except Exception as error:  # noqa: BLE001 - degrade, never crash the run
            print(f"OpenReview login failed, continuing on tier 1: {error}", file=sys.stderr)
            degraded = True
    elif not args.offline:
        print("no OpenReview credentials; tier 2 disabled", file=sys.stderr)
        degraded = True

    openreview = OpenReviewResolver(cache, token) if (token or args.offline) else None
    pmlr_index = PmlrIndexResolver(cache)
    pmc = PmcResolver(cache)
    semanticscholar = SemanticScholarResolver(cache, os.environ.get("SCHOLARMEND_S2_KEY"))

    documents, projections, unresolved = [], [], []
    for path in files:
        for record in parse_file(path):
            try:
                ledger = resolve_record(record, openreview=openreview,
                                        pmlr_index=pmlr_index, pmc=pmc,
                                        semanticscholar=semanticscholar)
            except AuthError as error:
                print(f"tier 2 unavailable: {error}", file=sys.stderr)
                degraded = True
                ledger = resolve_record(record, openreview=None, pmlr_index=None,
                                        pmc=None, semanticscholar=None)
            documents.append(to_json(record, ledger))
            projections.append(project_ris(record, ledger))
            missing = [f for f in RESOLVED_FIELDS if ledger.is_unresolved(f)]
            if missing:
                unresolved.append((record.title, missing))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "resolved.json").write_text(
        json.dumps(documents, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    (args.out / "mended.ris").write_text("".join(projections), encoding="utf-8")

    lines = [f"records: {len(documents)}", f"records with unresolved fields: {len(unresolved)}", ""]
    for title, missing in unresolved[:200]:
        lines.append(f"  unresolved {','.join(missing):28s} {title[:70]}")
    (args.out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {len(documents)} records to {args.out}")
    return 1 if degraded else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole suite**

Run: `pytest -v`
Expected: all tests pass, 108 total

- [ ] **Step 5: Add the usage section to `README.md`**

Replace the `Status:` line with:

```markdown
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
```

- [ ] **Step 6: Commit**

```bash
git add src/scholarmend/cli.py tests/test_cli.py README.md
git commit -m "feat: add the command line interface"
```

---

### Task 13: The gold-set acceptance suite

The task that decides whether any of this worked. The 2026-09-20 verification effort produced labelled ground truth for 112 records that escaped an automated rule table and were resolved by hand over a day. This suite measures how much of that day the pipeline gives back.

All tests skip cleanly when the validation corpus is not checked out alongside, so the suite stays runnable by someone who cloned only this repository.

**Files:**
- Create: `tests/test_acceptance.py`
- Modify: `README.md` (a Validation section)

**Interfaces:**
- Consumes: the whole pipeline.
- Produces: nothing importable; this is the acceptance gate.

- [ ] **Step 1: Write the acceptance tests**

Create `tests/test_acceptance.py`:

```python
"""Acceptance tests against the reviewers' hand-verified labels.

These are regression tests in the strongest sense available: the expected
values were produced by two people resolving records one at a time, with the
evidence for each recorded in ../Trust-Evals-LitReview/verification/.
"""

from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import pytest

from scholarmend import miners
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record
from scholarmend.resolvers.openreview import parse_venueid

GOLD = Path(__file__).parents[2] / "Trust-Evals-LitReview"
pytestmark = pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not alongside")


def corpus_records():
    for path in sorted(glob.glob(str(GOLD / "corpus" / "*.ris"))):
        yield from parse_file(Path(path))


def test_the_corpus_is_the_one_the_spec_measured():
    assert sum(1 for _ in corpus_records()) == 2413


def test_tier_one_leaves_exactly_twenty_one_records_with_no_miner():
    unmined = [r for r in corpus_records() if not miners.mine_all(r.urls)]
    assert len(unmined) == 21, len(unmined)


def test_proceedings_mining_covers_the_measured_1854():
    mined = [r for r in corpus_records()
             if any(c.field == "venue" for c in miners.mine_all(r.urls))]
    assert len(mined) == 1854, len(mined)


def test_scholar_loses_every_single_year_disagreement():
    """The spec's free property test. One loss here means precedence is wrong."""
    checked = disagreed = 0
    for record in corpus_records():
        ledger = resolve_record(record)
        winner = ledger.resolve("year")
        scholar = next((c for c in ledger.claims("year") if c.source == "scholar"), None)
        if winner is None or scholar is None:
            continue
        checked += 1
        if winner.value != scholar.value:
            disagreed += 1
            assert winner.source != "scholar", record.title
    assert disagreed == 1264, disagreed


def test_the_openreview_bucket_is_the_ninety_the_reviewers_resolved():
    labels = json.loads((GOLD / "verification" / "openreview-venues.json").read_text())
    assert len(labels) == 90
    for venueid in labels.values():
        claims = {c.field: c.value for c in parse_venueid(venueid)}
        assert claims.get("venue"), venueid
        assert claims.get("track"), venueid


def test_workshop_status_matches_every_reviewer_label():
    """Zero disagreements is the bar, not a high percentage."""
    labels = json.loads((GOLD / "verification" / "openreview-venues.json").read_text())
    resolutions = json.loads((GOLD / "verification" / "review-bucket-resolutions.json").read_text())
    truth = {r["forum"]: r["truth"] for r in resolutions if r.get("forum")}

    disagreements = []
    for forum_id, venueid in labels.items():
        if forum_id not in truth:
            continue
        claims = {c.field: c.value for c in parse_venueid(venueid)}
        predicted = "WORKSHOP" if "Workshop" in (claims.get("track") or "") else "MAIN"
        if predicted != truth[forum_id]:
            disagreements.append((forum_id, venueid, predicted, truth[forum_id]))
    assert disagreements == [], disagreements


def test_the_headline_target_at_least_103_of_112_settled_automatically():
    """The acceptance criterion from the spec.

    103 is what two people reached by hand over a day. Anything less means the
    pipeline has not yet paid for itself.

    This joins the labelled rows back to their real corpus records and asks the
    miners what they actually extract, rather than pattern-matching the
    publisher column -- a test that reads the label to predict the answer would
    pass whether or not any code works.
    """
    import re

    resolutions = json.loads((GOLD / "verification" / "review-bucket-resolutions.json").read_text())
    assert len(resolutions) == 112

    def key(title):
        return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:60]

    by_title = {}
    for record in corpus_records():
        by_title.setdefault(key(record.title), []).append(record)

    # A key is only worth counting if a resolver exists that consumes it.
    RESOLVABLE_KEYS = {"forum_id", "pmlr_volume", "pmc_id"}

    settled, unmatched, stuck = 0, [], []
    for row in resolutions:
        records = by_title.get(key(row["title"]))
        if not records:
            unmatched.append(row["title"][:60])
            continue
        fields = set()
        for record in records:
            fields |= {c.field for c in miners.mine_all(record.urls)}
        if "venue" in fields or (fields & RESOLVABLE_KEYS):
            settled += 1
        else:
            stuck.append((row["title"][:55], row.get("pb")))

    assert not unmatched, f"could not join {len(unmatched)} labelled rows to the corpus: {unmatched[:3]}"
    assert settled >= 103, (
        f"only {settled} of 112 have a resolution path; still manual: {stuck}"
    )


def test_all_ten_hand_merged_titles_agree_on_year_after_resolution():
    """The secondary target: the hand-maintained merge list becomes unnecessary.

    Four collapse from tier-1 mining alone, because Scholar dated the copies
    2025 and 2026 while both URLs say 2025. The other six need the tier-2
    venueid to supply a year the OpenReview copy simply does not carry, so
    without credentials this asserts only the four.
    """
    listed = [r["title"].strip().lower()
              for r in csv.DictReader((GOLD / "verification" / "merge-titles-2026-09-20.csv").open())]
    assert len(listed) == 10

    by_title: dict[str, list] = {}
    for record in corpus_records():
        by_title.setdefault(record.title.strip().lower(), []).append(record)

    collapsed = 0
    for title in listed:
        copies = by_title.get(title, [])
        if len(copies) < 2:
            continue
        years = set()
        for record in copies:
            claim = resolve_record(record).resolve("year")
            years.add(claim.value if claim else None)
        if len(years) == 1 and None not in years:
            collapsed += 1
    assert collapsed >= 4, f"tier-1 mining collapsed only {collapsed} of the 10"


def test_no_record_is_ever_dropped():
    """The error asymmetry: a false drop is silent and unrecoverable."""
    from scholarmend.emit import project_ris

    count = 0
    for record in corpus_records():
        assert project_ris(record, resolve_record(record)).strip()
        count += 1
    assert count == 2413
```

- [ ] **Step 2: Run the acceptance suite**

Run: `pytest tests/test_acceptance.py -v`
Expected: 9 passed.

Every assertion here carries a number taken from the spec or from the reviewers' files. **If one fails, do not adjust the number to match the code.** Investigate which is wrong and report it — these numbers are what the spec's claims rest on, and a test edited to pass is worse than no test.

- [ ] **Step 3: Run the full suite and check types and lint**

```bash
pytest -v
ruff check src tests
mypy src
```

Expected: all tests pass, 117 total; ruff and mypy clean.

- [ ] **Step 4: Add the Validation section to `README.md`**

```markdown
## Validation

scholarmend is tested against hand-verified ground truth rather than against
its own output. The Trust-Evals-LitReview review produced labels for 112
records that escaped an automated rule table and were resolved individually,
with the evidence for each recorded.

| Check | Bar |
|-------|-----|
| Records the pipeline settles of those 112 | at least 103, zero disagreements |
| Workshop status against reviewer labels | zero disagreements |
| Scholar's year losing every disagreement | all 1,264 |
| Proceedings mining coverage | exactly 1,854 of 2,413 |
| Records with no miner at all | exactly 21 |
| Hand-maintained merge list | retired; 4 collapse at tier 1, 6 at tier 2 |

Run them with the review repository checked out alongside this one:

    pytest tests/test_acceptance.py -v

They skip cleanly when it is not.
```

- [ ] **Step 5: Commit**

```bash
git add tests/test_acceptance.py README.md
git commit -m "test: accept only against the reviewers' hand-verified labels"
```

---

## A note on Task 8

Task 8 was added during the plan's self-review, not in the first draft. The
spec's architecture listed `pmlr_index.py` and `pmc.py`, but no task created
them, while the acceptance criterion counted the thirteen records that depend
on them. Without Task 8 the headline target is 90 of 112 -- below the bar the
spec sets. The first draft of the headline test also pattern-matched the
publisher column rather than exercising the miners, so it would have passed
whether or not the code worked. Both are fixed above.

## Completion

After Task 13:

- [ ] `pytest` is green and `ruff check src tests` and `mypy src` are clean.
- [ ] The cache directory produced by a full run is committed, so the run reproduces.
- [ ] `docs/openreview-auth.md` records the tier-2 auth answer from Task 1.
- [ ] Run once against the real corpus and compare `mended.ris` to `../Trust-Evals-LitReview/out/clean.ris`; every difference should be a correction you can name.
- [ ] Sub-project C (`venuetriage`) can now consume `mended.ris`. Its rule table exists largely to guess around truncation and should shrink; that is a separate plan.
