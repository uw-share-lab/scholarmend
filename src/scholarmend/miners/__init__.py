"""The miner registry.

Order matters only for readability; miners are disjoint by host, so at most one
answers any given URL.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from ..models import Claim
from . import arxiv, openreview, pmc, pmlr, proceedings

ALL: tuple[Callable[[str], list[Claim]], ...] = (
    proceedings.mine,
    openreview.mine,
    pmlr.mine,
    arxiv.mine,
    pmc.mine,
)


def mine_all(urls: Iterable[str]) -> list[Claim]:
    """Every claim every miner can make about every URL on a record."""
    claims: list[Claim] = []
    for url in urls:
        for miner in ALL:
            claims.extend(miner(url))
    return claims
