"""Claim accumulation and resolution.

The precedence table is the whole policy, and it is data. A source listed for
a field may answer it, best first; a source *absent* from a field's tuple is
excluded from answering it at all. That single mechanism expresses both
ordering and exclusion -- notably that preprint-derived sources may supply an
abstract and a full author list, which preprints genuinely have, but must never
supply a venue or a year, which they get wrong by construction.
"""

from __future__ import annotations

from collections import defaultdict

from .models import Claim

PRECEDENCE: dict[str, tuple[str, ...]] = {
    # Scholar loses all 1,264 year disagreements measured on the corpus.
    "year": ("proceedings_url", "openreview_api", "pmlr_index", "semanticscholar", "scholar"),
    # The OpenReview venueid was correct in 92 of 92 hand-checked cases.
    "venue": ("openreview_api", "proceedings_url", "pmlr_index", "semanticscholar", "scholar"),
    "track": ("openreview_api", "proceedings_url"),
    # pmlr_index emits "PMLR v318" as a venue_id too. Listing only
    # openreview_api here made resolve("venue_id") return None for every
    # PMLR record, discarding the identity evidence a human adjudicating
    # one of them needs.
    "venue_id": ("openreview_api", "pmlr_index"),
    "version": ("proceedings_url", "openreview_api", "pmlr_index", "arxiv_url"),
    # Preprint sources are welcome here: Scholar truncates 71% of author lists.
    "authors": ("openreview_api", "semanticscholar", "openalex", "arxiv_url", "scholar"),
    "abstract": ("openreview_api", "semanticscholar", "openalex", "arxiv_url", "scholar"),
    "doi": ("openreview_api", "semanticscholar", "openalex", "arxiv_url"),
    # Keys, not answers: these carry an identifier from tier 1 to tier 2.
    "forum_id": ("openreview_url",),
    "pmlr_volume": ("pmlr_url", "pmc_api"),
    "arxiv_id": ("arxiv_url",),
    "pmc_id": ("pmc_url",),
}


class Ledger:
    """Every claim made about one record, and the policy for choosing between them."""

    def __init__(self) -> None:
        self._claims: dict[str, list[Claim]] = defaultdict(list)

    def add(self, claim: Claim) -> None:
        if claim not in self._claims[claim.field]:
            self._claims[claim.field].append(claim)

    def claims(self, field: str) -> list[Claim]:
        """Every claim for ``field``, including ones excluded by precedence."""
        return list(self._claims.get(field, []))

    def resolve(self, field: str) -> Claim | None:
        """The winning claim, or ``None`` if no permitted source answered."""
        order = PRECEDENCE.get(field)
        if not order:
            return None
        for source in order:
            for claim in self._claims.get(field, []):
                if claim.source == source:
                    return claim
        return None

    def is_unresolved(self, field: str) -> bool:
        return self.resolve(field) is None

    def conflicts(self) -> list[str]:
        """Fields where two sources *at the same tier* disagree.

        Cross-tier disagreement is the normal case -- Scholar against a mined
        URL happens 1,264 times in the corpus -- so flagging it would drown the
        report. Same-tier disagreement means two equally trusted sources cannot
        both be right, which is worth a human's attention.
        """
        out = []
        for field, claims in self._claims.items():
            by_tier: dict[int, set[str]] = defaultdict(set)
            for claim in claims:
                by_tier[claim.tier].add(claim.value)
            if any(len(values) > 1 for values in by_tier.values()):
                out.append(field)
        return sorted(out)
