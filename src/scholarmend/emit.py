"""Canonical JSON, and the RIS projection derived from it.

The JSON is the record. RIS cannot represent provenance, so it is emitted as a
projection for the tools that need it -- Covidence, and venuetriage -- by
rewriting only the lines whose values scholarmend corrected, and inserting a
line for a corrected field the record never carried. Every other byte of the
original record survives, which is what makes the projection safe to feed to a
parser that was written against Scholar's exact output.
"""

from __future__ import annotations

import re

from .ledger import PRECEDENCE, Ledger
from .models import Record
from .pipeline import RESOLVED_FIELDS

# Which RIS tag carries each resolved field. Only these are ever rewritten.
#
# Authors and abstracts are deliberately absent. Rewriting AU means deleting N
# lines and inserting M -- restructuring a repeated field -- which is a
# different act from substituting one line or inserting one missing line, and
# puts the round-trip guarantee -- the projection's whole safety argument -- at
# risk. Resolved authors and abstracts live in the canonical JSON, which is the
# record; RIS is a projection for tools that cannot read it.
_TAG_FOR = {"year": "PY", "venue": "JF"}


def to_json(record: Record, ledger: Ledger) -> dict:
    """The canonical record: winning values, and every claim behind them."""
    fields: dict[str, dict[str, object]] = {}
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
    # Every field the precedence table knows about, not a hand-listed subset.
    # The subset dropped pmlr_volume, pmc_id and arxiv_id from the canonical
    # JSON entirely -- losing the evidence on exactly the records a human has
    # to adjudicate, which are the ones no resolver settled.
    claims = [
        {"field": c.field, "value": c.value, "source": c.source,
         "tier": c.tier, "confidence": c.confidence, "evidence": c.evidence}
        for field in sorted(set(PRECEDENCE) | set(RESOLVED_FIELDS))
        for c in ledger.claims(field)
    ]
    return {
        "title": record.title,
        "source_file": record.source_file,
        "fields": fields,
        "claims": claims,
        "conflicts": ledger.conflicts(),
    }


def _line(tag: str, value: str) -> str:
    """One RIS line, preserving Scholar's ``2025///`` year shape."""
    if tag == "PY":
        return f"PY  - {value}///"
    return f"{tag}  - {value}"


def _insert_at(lines: list[str]) -> int:
    """Where a missing tag's line goes: immediately before ``ER  - ``.

    A record with no ``ER`` line at all is malformed, but refusing to emit it
    would be a false drop -- the failure mode the design calls silent and
    unrecoverable -- so the line is appended after the last non-blank line
    instead, which keeps the record's trailing newline where it was.
    """
    for index, line in enumerate(lines):
        if line.startswith("ER  -"):
            return index
    last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
    return last + 1


def project_ris(record: Record, ledger: Ledger) -> str:
    """``record.raw`` with corrected fields rewritten and nothing else touched.

    A tag that already has a line is substituted in place. A tag that has none
    is inserted immediately before ``ER  - ``: 331 corpus records -- every one
    of them from OpenReview -- carry no ``PY`` line at all, which is precisely
    the population tier 2 exists to supply a year for, and substitution alone
    would drop every year it resolved for them.

    Inserting one line is not the same as restructuring a multi-line field.
    ``AU`` and ``AB`` stay out of ``_TAG_FOR`` for exactly that reason.
    """
    corrections = {}
    for field, tag in _TAG_FOR.items():
        claim = ledger.resolve(field)
        if claim is not None and claim.source != "scholar":
            corrections[tag] = claim.value
    if not corrections:
        return record.raw

    out = []
    substituted = set()
    for line in record.raw.split("\n"):
        match = re.match(r"^([A-Z][A-Z0-9])  - ", line)
        line_tag: str | None = match.group(1) if match else None
        if line_tag in corrections:
            substituted.add(line_tag)
            out.append(_line(line_tag, corrections[line_tag]))
        else:
            out.append(line)

    missing = [tag for tag in _TAG_FOR.values() if tag in corrections and tag not in substituted]
    if missing:
        index = _insert_at(out)
        out[index:index] = [_line(tag, corrections[tag]) for tag in missing]
    return "\n".join(out)
