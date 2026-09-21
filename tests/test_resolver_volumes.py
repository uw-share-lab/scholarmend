from __future__ import annotations

from scholarmend.cache import Cache
from scholarmend.miners import pmc as pmc_miner
from scholarmend.resolvers.pmc import PmcResolver
from scholarmend.resolvers.pmlr_index import PmlrIndexResolver, title_from_html, venue_from_title


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_pmc_url_yields_the_pmc_id():
    claims = pmc_miner.mine("https://pmc.ncbi.nlm.nih.gov/articles/PMC13004626/")
    assert value(claims, "pmc_id") == "PMC13004626"


def test_pmc_miner_ignores_other_hosts():
    assert pmc_miner.mine("https://arxiv.org/abs/2501.00001") == []


def test_pmc_miner_rejects_a_lookalike_host():
    # endswith("ncbi.nlm.nih.gov") would accept these; exact membership must not.
    assert pmc_miner.mine("https://notncbi.nlm.nih.gov/articles/PMC99999999/") == []
    assert pmc_miner.mine("https://evilncbi.nlm.nih.gov/articles/PMC12345678/") == []


def test_pmc_miner_rejects_a_suffix_domain_trick():
    assert pmc_miner.mine("https://ncbi.nlm.nih.gov.attacker.com/articles/PMC1/") == []


def test_pmc_miner_accepts_the_bare_and_www_hosts():
    assert pmc_miner.mine("https://ncbi.nlm.nih.gov/articles/PMC13004626/")
    assert pmc_miner.mine("https://www.ncbi.nlm.nih.gov/articles/PMC13004626/")


def test_venue_from_title_recognises_an_icml_volume():
    title = "Proceedings of the 42nd International Conference on Machine Learning"
    assert venue_from_title(title) == "ICML"


def test_venue_from_title_recognises_neurips_and_iclr():
    assert venue_from_title("Advances in Neural Information Processing Systems 38") == "NeurIPS"
    assert venue_from_title("Proceedings of the International Conference on Learning Representations") == "ICLR"


def test_venue_from_title_leaves_an_unrelated_conference_alone():
    # v318 is the Canadian Conference on AI: out of scope, and it must not be
    # coerced into one of the three venues under review.
    assert venue_from_title("Proceedings of the Canadian Conference on AI") is None


def test_title_from_html_reads_an_h2_heading():
    # Real markup from proceedings.mlr.press/v318/.
    html = ("<h2>Volume 318: The 39th Canadian Conference on Artificial "
            "Intelligence, 25-29 May 2026, Simon ...</h2>")
    assert title_from_html(html) == (
        "The 39th Canadian Conference on Artificial Intelligence, "
        "25-29 May 2026, Simon ..."
    )


def test_title_from_html_reads_an_h1_heading():
    html = "<h1>Proceedings of the 42nd International Conference on Machine Learning</h1>"
    assert title_from_html(html) == "Proceedings of the 42nd International Conference on Machine Learning"


def test_title_from_html_with_neither_heading_is_empty():
    assert title_from_html("<div>no heading here</div>") == ""


def test_title_from_html_strips_the_volume_number_prefix():
    html = "<h2>Volume 267: Proceedings of the 42nd International Conference on Machine Learning</h2>"
    title = title_from_html(html)
    assert not title.startswith("Volume")
    assert title == "Proceedings of the 42nd International Conference on Machine Learning"


def test_the_canadian_conference_title_from_an_h2_page_stays_unresolved_to_a_venue():
    html = ("<h2>Volume 318: The 39th Canadian Conference on Artificial "
            "Intelligence, 25-29 May 2026, Simon ...</h2>")
    assert venue_from_title(title_from_html(html)) is None


def test_an_icml_title_from_an_h1_page_resolves_to_icml():
    html = "<h1>Volume 267: Proceedings of the 42nd International Conference on Machine Learning</h1>"
    assert venue_from_title(title_from_html(html)) == "ICML"


def test_pmlr_index_resolves_a_cached_volume(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:267",
              {"title": "Proceedings of the 42nd International Conference on Machine Learning"})
    claims = PmlrIndexResolver(cache).resolve("267")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "version") == "proceedings"


def test_pmlr_index_keeps_the_raw_title_as_evidence(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})
    claims = PmlrIndexResolver(cache).resolve("318")
    assert any("Canadian" in c.evidence for c in claims)


def test_an_out_of_scope_volume_still_reports_its_proceedings_title(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})
    claims = PmlrIndexResolver(cache).resolve("318")
    assert value(claims, "venue_id") == "PMLR v318"


def test_an_out_of_scope_volume_emits_no_venue_claim(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:318", {"title": "Proceedings of the Canadian Conference on AI"})
    claims = PmlrIndexResolver(cache).resolve("318")
    assert value(claims, "venue") is None          # never coerced onto a known venue
    assert value(claims, "venue_id") == "PMLR v318"  # but evidence is still carried forward


def test_pmc_resolver_returns_the_pmlr_volume(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmc:esummary:PMC13004626",
              {"result": {"PMC13004626": {"volume": "267"}}})
    assert value(PmcResolver(cache).resolve("PMC13004626"), "pmlr_volume") == "267"


def test_pmc_resolver_handles_a_result_keyed_by_the_bare_numeric_id(tmp_path):
    # esummary keys its result by either "PMC13004626" or "13004626"; the
    # fallback branch is the only thing that reads the second form.
    cache = Cache(tmp_path)
    cache.put("pmc:esummary:PMC13004626", {"result": {"13004626": {"volume": "267"}}})
    assert value(PmcResolver(cache).resolve("PMC13004626"), "pmlr_volume") == "267"


def test_pmc_resolver_with_no_volume_yields_nothing(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmc:esummary:PMC1", {"result": {"PMC1": {}}})
    assert PmcResolver(cache).resolve("PMC1") == []


def test_volume_claims_are_tier_two(tmp_path):
    cache = Cache(tmp_path)
    cache.put("pmlr:volume:267", {"title": "Proceedings of the 42nd International Conference on Machine Learning"})
    assert all(c.tier == 2 for c in PmlrIndexResolver(cache).resolve("267"))
