"""Canonical JSON, and the RIS projection derived from it.

The JSON is the record. RIS cannot represent provenance, so it is emitted as a
projection for the tools that need it -- Covidence, and venuetriage -- by
rewriting only the lines whose values scholarmend corrected. Every other byte
of the original record survives, which is what makes the projection safe to
feed to a parser that was written against Scholar's exact output.
"""

from __future__ import annotations

import re

from .ledger import Ledger
from .models import Record
from .pipeline import RESOLVED_FIELDS

# Which RIS tag carries each resolved field. Only these are ever rewritten.
#
# Authors and abstracts are deliberately absent. Rewriting AU means deleting N
# lines and inserting M, which is far more invasive than substituting a line in
# place and puts the round-trip guarantee -- the projection's whole safety
# argument -- at risk. Resolved authors and abstracts live in the canonical
# JSON, which is the record; RIS is a projection for tools that cannot read it.
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
