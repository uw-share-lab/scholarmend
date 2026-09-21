from __future__ import annotations

from scholarmend.ledger import PRECEDENCE, Ledger
from scholarmend.models import Claim


def c(field, value, source, tier, conf=1.0, evidence="e"):
    return Claim(field=field, value=value, source=source, tier=tier,
                 confidence=conf, evidence=evidence)


def test_claim_is_hashable_and_compares_by_value():
    a = c("year", "2025", "proceedings_url", 1)
    b = c("year", "2025", "proceedings_url", 1)
    assert a == b
    assert len({a, b}) == 1


def test_higher_precedence_source_wins():
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert led.resolve("year").value == "2025"


def test_losing_claims_are_retained():
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert {cl.value for cl in led.claims("year")} == {"2025", "2026"}


def test_a_source_absent_from_a_fields_precedence_cannot_answer_it():
    # arxiv may supply authors but must never supply venue.
    led = Ledger()
    led.add(c("venue", "arXiv (Cornell University)", "arxiv_url", 3))
    assert led.resolve("venue") is None
    assert led.is_unresolved("venue") is True


def test_that_same_source_may_still_answer_a_field_it_is_listed_for():
    led = Ledger()
    led.add(c("authors", "A; B; C", "arxiv_url", 3))
    assert led.resolve("authors").value == "A; B; C"


def test_disagreement_within_one_tier_is_a_conflict():
    led = Ledger()
    led.add(c("venue", "ICML", "openreview_api", 2))
    led.add(c("venue", "NeurIPS", "pmlr_index", 2))
    assert "venue" in led.conflicts()


def test_disagreement_across_tiers_is_not_a_conflict():
    # Scholar disagreeing with a mined URL is the expected case, 1,264 times
    # over in the real corpus. Flagging it would make the report useless.
    led = Ledger()
    led.add(c("year", "2026", "scholar", 0))
    led.add(c("year", "2025", "proceedings_url", 1))
    assert led.conflicts() == []


def test_agreement_within_a_tier_is_not_a_conflict():
    led = Ledger()
    led.add(c("venue", "ICML", "openreview_api", 2))
    led.add(c("venue", "ICML", "pmlr_index", 2))
    assert led.conflicts() == []


def test_unknown_field_resolves_to_none():
    assert Ledger().resolve("nonsense") is None


def test_precedence_puts_proceedings_url_above_scholar_for_year():
    assert PRECEDENCE["year"].index("proceedings_url") < PRECEDENCE["year"].index("scholar")


def test_precedence_excludes_preprint_sources_from_venue_and_year():
    for field in ("venue", "year"):
        assert "arxiv_url" not in PRECEDENCE[field]
        assert "openalex" not in PRECEDENCE[field]


def test_key_fields_exist_so_tier_one_can_hand_identifiers_to_tier_two():
    for field in ("forum_id", "pmlr_volume", "arxiv_id", "pmc_id"):
        assert field in PRECEDENCE


def test_a_pmlr_venue_id_resolves_through_the_ledger(tmp_path):
    """Not merely emitted -- resolved.

    The resolver has always produced "PMLR v318", but venue_id's precedence
    listed only openreview_api, so the ledger returned None for it on every
    PMLR record and the claim was configuration-dead.
    """
    from scholarmend.cache import Cache
    from scholarmend.resolvers.pmlr_index import PmlrIndexResolver

    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})

    led = Ledger()
    for claim in PmlrIndexResolver(cache).resolve("318"):
        led.add(claim)

    resolved = led.resolve("venue_id")
    assert resolved is not None and resolved.value == "PMLR v318"
    assert resolved.source == "pmlr_index"
