from __future__ import annotations

from scholarmend.cache import Cache
from scholarmend.resolvers.semanticscholar import (
    SemanticScholarResolver,
    _normalise,
    titles_match,
)


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def key_for(title: str) -> str:
    """Build the cache key exactly as the resolver builds it.

    Never hardcode a key literal here. ``_normalise`` strips everything
    non-alphanumeric, so a literal like ``"s2:search:some paper"`` misses the
    cache, the loader runs, and the test silently makes a real network call --
    which is how this file first went red against a live 429.
    """
    return f"s2:search:{_normalise(title)[:80]}"


def test_titles_match_ignores_case_and_punctuation():
    assert titles_match("Mind2Web 2: Evaluating Agentic Search", "mind2web 2 evaluating agentic search")


def test_titles_match_rejects_a_different_paper():
    assert not titles_match("Attention Is All You Need", "Attention Considered Harmful")


def test_resolve_returns_venue_and_year_from_cache(tmp_path):
    cache = Cache(tmp_path)
    cache.put(
        key_for("Attention Is All You Need"),
        {"data": [{"title": "Attention Is All You Need", "year": 2017,
                   "venue": "Neural Information Processing Systems",
                   "externalIds": {"DOI": "10.5555/3295222"}}]},
    )
    claims = SemanticScholarResolver(cache).resolve("Attention Is All You Need")
    assert value(claims, "venue") == "Neural Information Processing Systems"
    assert value(claims, "year") == "2017"
    assert value(claims, "doi") == "10.5555/3295222"


def test_a_title_that_does_not_match_is_discarded(tmp_path):
    cache = Cache(tmp_path)
    cache.put(key_for('Some Paper'), {"data": [{"title": "A Totally Different Paper",
                                                 "year": 2020, "venue": "ICML"}]})
    assert SemanticScholarResolver(cache).resolve("Some Paper") == []


def test_an_empty_result_yields_no_claims(tmp_path):
    cache = Cache(tmp_path)
    cache.put(key_for('Nothing Here'), {"data": []})
    assert SemanticScholarResolver(cache).resolve("Nothing Here") == []


def test_claims_are_tier_three_and_lower_confidence(tmp_path):
    cache = Cache(tmp_path)
    cache.put(key_for('X'), {"data": [{"title": "X", "year": 2021, "venue": "ICLR"}]})
    for claim in SemanticScholarResolver(cache).resolve("X"):
        assert claim.tier == 3
        assert claim.confidence < 0.9
