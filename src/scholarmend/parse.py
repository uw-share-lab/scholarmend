"""RIS in, RIS out, with the original text preserved exactly.

A record starts at a line beginning ``TY  - `` and runs until the next one.
That rule is what makes ``emit_ris(parse_ris(t)) == t`` true by construction
rather than by careful re-serialisation.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path

from .models import Record

_RECORD_START = re.compile(r"(?m)^TY  - ")
_FIELD = re.compile(r"(?m)^([A-Z][A-Z0-9])  - (.*)$")


def parse_ris(text: str, source_file: str) -> list[Record]:
    """Split ``text`` into records, keeping each one's original slice."""
    starts = [m.start() for m in _RECORD_START.finditer(text)]
    if not starts:
        # A blank file is genuinely empty. A file with content but no TY line
        # is a file that silently vanishes -- the false-drop direction, which
        # is unrecoverable because nothing downstream can tell it apart from a
        # corpus that never contained those records.
        if text.strip():
            raise ValueError(
                f"{source_file}: {len(text)} bytes but no 'TY  - ' line; "
                f"refusing to drop the whole file"
            )
        return []
    if text[: starts[0]].strip():
        raise ValueError(f"{source_file}: content before the first record; refusing to guess")

    records = []
    bounds = starts + [len(text)]
    for begin, end in pairwise(bounds):
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
