"""Per-field escalation through the tiers.

The escalation is per *field*, not per record. A NeurIPS record whose URL
already yielded venue, year and track makes no network call for those fields
even if its abstract is still a Scholar snippet. That is what keeps an evidence
ledger as cheap as a plain first-wins cascade.
"""

from __future__ import annotations

from . import miners
from .ledger import Ledger
from .models import Claim, Record

CONFIDENCE_FLOOR = 0.80

RESOLVED_FIELDS = (
    "venue", "year", "track", "version", "authors", "abstract", "doi", "venue_id",
)

_SCHOLAR_FIELDS = {
    "venue": lambda r: r.venue,
    "year": lambda r: r.year,
    "authors": lambda r: "; ".join(r.fields.get("AU", [])),
    "abstract": lambda r: r.first("AB"),
}


def scholar_claims(record: Record) -> list[Claim]:
    """Tier-0 claims: what Scholar says, retained as evidence and outranked."""
    claims = []
    for field, read in _SCHOLAR_FIELDS.items():
        value = read(record)
        if value:
            claims.append(
                Claim(field=field, value=value, source="scholar", tier=0,
                      confidence=0.30, evidence=f"{record.source_file}:TI={record.title[:40]}")
            )
    return claims


def _needs_escalation(ledger: Ledger, field: str) -> bool:
    claim = ledger.resolve(field)
    return claim is None or claim.confidence < CONFIDENCE_FLOOR


def resolve_record(
    record: Record,
    openreview=None,
    pmlr_index=None,
    pmc=None,
    semanticscholar=None,
) -> Ledger:
    """Build the full claim ledger for one record."""
    ledger = Ledger()

    for claim in scholar_claims(record):
        ledger.add(claim)
    for claim in miners.mine_all(record.urls):
        ledger.add(claim)

    def unsettled() -> bool:
        return any(_needs_escalation(ledger, f) for f in ("venue", "year", "track"))

    # Tier 2: only when a key exists and a field tier 1 could not settle remains.
    forum = ledger.resolve("forum_id")
    if openreview is not None and forum is not None and unsettled():
        for claim in openreview.resolve(forum.value):
            ledger.add(claim)

    # PMC is a bridge, not a destination: it yields a PMLR volume, which the
    # index then turns into a venue. Run it before the index for that reason.
    pmc_id = ledger.resolve("pmc_id")
    if pmc is not None and pmc_id is not None and unsettled():
        for claim in pmc.resolve(pmc_id.value):
            ledger.add(claim)

    volume = ledger.resolve("pmlr_volume")
    if pmlr_index is not None and volume is not None and unsettled():
        for claim in pmlr_index.resolve(volume.value):
            ledger.add(claim)

    # Tier 3: last resort, for records no miner covered.
    if (
        semanticscholar is not None
        and record.title
        and any(_needs_escalation(ledger, f) for f in ("venue", "year"))
    ):
        for claim in semanticscholar.resolve(record.title):
            ledger.add(claim)

    return ledger
