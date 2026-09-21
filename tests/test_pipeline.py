from __future__ import annotations

from pathlib import Path

from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record, scholar_claims

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


class SpyOpenReview:
    def __init__(self, claims=()):
        self.calls = []
        self._claims = list(claims)

    def resolve(self, forum_id):
        self.calls.append(forum_id)
        return self._claims


def records():
    return parse_file(FIXTURE)


def test_scholar_claims_are_tier_zero():
    for claim in scholar_claims(records()[0]):
        assert claim.tier == 0
        assert claim.source == "scholar"


def test_scholar_year_claim_carries_the_wrong_year_it_really_has():
    claims = {c.field: c.value for c in scholar_claims(records()[0])}
    assert claims["year"] == "2026"


def test_the_url_beats_scholar_on_year():
    ledger = resolve_record(records()[0])
    assert ledger.resolve("year").value == "2025"


def test_the_losing_scholar_claim_is_still_there():
    ledger = resolve_record(records()[0])
    assert {c.value for c in ledger.claims("year")} == {"2025", "2026"}


def test_venue_comes_from_the_url_not_the_ellipsis():
    ledger = resolve_record(records()[0])
    assert ledger.resolve("venue").value == "NeurIPS"


def test_a_fully_mined_record_never_calls_tier_two():
    spy = SpyOpenReview()
    resolve_record(records()[0], openreview=spy)
    assert spy.calls == []


def test_an_openreview_only_record_does_call_tier_two():
    from scholarmend.models import Claim

    spy = SpyOpenReview([
        Claim("venue", "ICLR", "openreview_api", 2, 0.99, "venueid=ICLR.cc/2026/Conference"),
        Claim("year", "2026", "openreview_api", 2, 0.99, "venueid=ICLR.cc/2026/Conference"),
    ])
    ledger = resolve_record(records()[2], openreview=spy)
    assert spy.calls == ["r0BFucF2dH"]
    assert ledger.resolve("venue").value == "ICLR"


def test_tier_two_is_skipped_when_no_resolver_is_supplied():
    # No credentials must degrade, never crash a 2,400-record run.
    ledger = resolve_record(records()[2], openreview=None)
    assert ledger.resolve("venue").value == "… on Learning Representations"


def test_a_record_with_no_resolvable_field_keeps_scholars_value():
    ledger = resolve_record(records()[2])
    assert ledger.is_unresolved("track")


def test_the_pdf_record_with_a_tracking_query_still_resolves():
    ledger = resolve_record(records()[3])
    assert ledger.resolve("year").value == "2025"


def test_pmc_runs_before_the_pmlr_index_so_the_bridge_works():
    """PMC yields a volume; only then can the index turn it into a venue."""
    from scholarmend.models import Claim
    from scholarmend.parse import parse_ris

    raw = (
        "TY  - JOUR\nTI  - Restoring calibration for aligned LLMs\n"
        "JF  - … Learning …\nPB  - pmc.ncbi.nlm.nih.gov\n"
        "UR  - https://pmc.ncbi.nlm.nih.gov/articles/PMC13004626/\nER  - \n"
    )
    record = parse_ris(raw, "t.ris")[0]

    class Pmc:
        def resolve(self, pmc_id):
            assert pmc_id == "PMC13004626"
            return [Claim("pmlr_volume", "267", "pmc_api", 2, 0.9, "e")]

    class Index:
        def __init__(self):
            self.seen = []

        def resolve(self, volume):
            self.seen.append(volume)
            return [Claim("venue", "ICML", "pmlr_index", 2, 0.95, "e")]

    index = Index()
    ledger = resolve_record(record, pmc=Pmc(), pmlr_index=index)
    assert index.seen == ["267"]
    assert ledger.resolve("venue").value == "ICML"
