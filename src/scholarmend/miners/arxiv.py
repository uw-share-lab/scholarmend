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
