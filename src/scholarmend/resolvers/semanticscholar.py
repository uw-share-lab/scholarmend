"""Semantic Scholar, the tier-3 fallback for records no miner covers.

Measured on a 30-title sample of this corpus, its hit rate was low but its
venue was correct on every hit -- unlike OpenAlex, which matched more titles
and described the arXiv preprint rather than the published paper in every case
where it named a venue at all. Low recall with high precision is the right
shape for a last resort, so its claims are admitted but marked down.
"""

from __future__ import annotations

import re
import time
import urllib.parse
from collections.abc import Callable

from ..cache import Cache
from ..models import Claim

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,venue,externalIds"

# An API key buys 1 request per second, and the anonymous pool is slower
# still. Back-to-back searches drew 429s even with a key, so requests are
# spaced a little wider than the limit.
MIN_INTERVAL = 1.1


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
    def __init__(
        self,
        cache: Cache,
        api_key: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.cache = cache
        self.api_key = api_key
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def _search(self, query: str, fields: str) -> dict:
        """One paced request. Only called on a cache miss, so a warm run never waits."""
        from ..http import get_json

        if self._last is not None:
            wait = MIN_INTERVAL - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        try:
            return get_json(f"{API}?query={urllib.parse.quote(query[:200])}&limit=1&fields={fields}",
                            headers=headers)
        finally:
            self._last = self._clock()

    def resolve(self, title: str) -> list[Claim]:
        def loader() -> dict:
            return self._search(title, FIELDS)

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

    def abstract(self, title: str) -> list[Claim]:
        """An abstract, for the few records no proceedings page or forum covers.

        A separate query and key from ``resolve``: widening ``FIELDS`` there
        would leave every committed search entry without the new field.
        """
        from .proceedings_page import one_line

        def loader() -> dict:
            return self._search(title, "title,abstract")

        payload = self.cache.fetch(abstract_key(title), loader)
        results = payload.get("data") or []
        if not results or not titles_match(title, results[0].get("title") or ""):
            return []
        text = one_line(results[0].get("abstract") or "")
        if not text:
            return []
        return [Claim(field="abstract", value=text, source="semanticscholar", tier=3,
                      confidence=0.75, evidence=f"s2:{results[0].get('title', '')[:60]}")]


def abstract_key(title: str) -> str:
    return f"s2:abstract:{_normalise(title)[:80]}"
