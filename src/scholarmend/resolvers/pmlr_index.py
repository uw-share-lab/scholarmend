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
    (re.compile(r"International Conference on Machine Learning", re.IGNORECASE), "ICML"),
    (re.compile(r"Neural Information Processing Systems", re.IGNORECASE), "NeurIPS"),
    (re.compile(r"International Conference on Learning Representations", re.IGNORECASE), "ICLR"),
)


def venue_from_title(title: str) -> str | None:
    for pattern, venue in _VENUES:
        if pattern.search(title):
            return venue
    return None


def title_from_html(html: str) -> str:
    """The volume page's heading, or ``""`` if neither heading is present.

    PMLR volume pages use ``<h1>`` on some volumes and ``<h2>`` on others
    (v318, for one, is an ``<h2>``); whichever appears first is taken. The
    heading reads ``"Volume NNN: <proceedings title>"``, and the ``"Volume
    NNN: "`` prefix is stripped since it is routing detail that
    ``venue_from_title`` has no use for and would otherwise have to ignore.
    """
    match = re.search(r"<h([12])[^>]*>(.*?)</h\1>", html, re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
    return re.sub(r"^Volume\s+\d+:\s*", "", title)


class PmlrIndexResolver:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def resolve(self, volume: str) -> list[Claim]:
        def loader() -> dict:
            import urllib.request

            with urllib.request.urlopen(INDEX.format(volume=volume), timeout=20) as response:
                html = response.read().decode("utf-8", "replace")
            return {"title": title_from_html(html)}

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
