"""PubMed Central as a bridge to a PMLR volume.

PMC records the volume of the proceedings an article appeared in. For three
corpus records that number was the only route to a venue, and the reviewers
followed it by hand: PMC citation_volume 267 -> PMLR v267 -> ICML 2025.
"""

from __future__ import annotations

from ..cache import Cache
from ..models import Claim

ESUMMARY = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=pmc&id={pmc_id}&retmode=json"
)


class PmcResolver:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    def resolve(self, pmc_id: str) -> list[Claim]:
        def loader() -> dict:
            from ..http import get_json

            return get_json(ESUMMARY.format(pmc_id=pmc_id.removeprefix("PMC")))

        payload = self.cache.fetch(f"pmc:esummary:{pmc_id}", loader)
        result = (payload.get("result") or {}).get(pmc_id) or {}
        # esummary keys the result by the bare numeric id as well.
        if not result:
            result = (payload.get("result") or {}).get(pmc_id.removeprefix("PMC")) or {}
        volume = result.get("volume")
        if not volume:
            return []
        return [
            Claim(field="pmlr_volume", value=str(volume), source="pmc_api", tier=2,
                  confidence=0.90, evidence=f"PMC esummary volume={volume}")
        ]
