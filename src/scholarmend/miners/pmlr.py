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
