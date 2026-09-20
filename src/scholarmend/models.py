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

    # Record holds a mutable ``fields`` dict, so it is deliberately not
    # hashable. Without this, frozen=True would auto-generate a __hash__
    # that raises a confusing "unhashable type: 'dict'" the first time
    # someone puts a Record in a set or uses one as a dict key. Identify
    # records by title or source_file, never by hashing.
    __hash__ = None

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
