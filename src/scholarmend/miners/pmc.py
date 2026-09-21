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
