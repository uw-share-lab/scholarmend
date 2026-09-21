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
