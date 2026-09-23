from __future__ import annotations

import pytest

from scholarmend.miners.proceedings import UnknownTrack, mine

NEURIPS_DB = (
    "https://proceedings.neurips.cc/paper_files/paper/2025/hash/"
    "4da4f3c0dd1b907c48e2119afb2e2fde-Abstract-Datasets_and_Benchmarks_Track.html"
)
ICLR = (
    "https://proceedings.iclr.cc/paper_files/paper/2026/hash/"
    "635a38ee326fb0464e0c2b1c1a0b0c1d-Abstract-Conference.html"
)
PDF_WITH_UTM = (
    "https://proceedings.iclr.cc/paper_files/paper/2025/file/"
    "aaaabbbbccccddddeeeeffff00001111-Paper-Conference.pdf?utm_source=chatgpt.com"
)


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_extracts_the_year_from_the_path_not_the_record():
    assert value(mine(NEURIPS_DB), "year") == "2025"


def test_extracts_the_venue_from_the_host():
    assert value(mine(NEURIPS_DB), "venue") == "NeurIPS"
    assert value(mine(ICLR), "venue") == "ICLR"


def test_extracts_the_track():
    assert value(mine(NEURIPS_DB), "track") == "Datasets_and_Benchmarks_Track"
    assert value(mine(ICLR), "track") == "Conference"


def test_the_pre_2024_benchmarks_spelling_is_the_same_track():
    # NeurIPS 2023 and earlier drop the "_Track" suffix from the path.
    url = (
        "https://proceedings.neurips.cc/paper_files/paper/2023/hash/"
        "f64e55d03e2fe61aa4114e49cb654acb-Abstract-Datasets_and_Benchmarks.html"
    )
    assert value(mine(url), "track") == "Datasets_and_Benchmarks_Track"
    assert value(mine(url), "year") == "2023"


def test_marks_the_record_as_proceedings_not_preprint():
    assert value(mine(ICLR), "version") == "proceedings"


def test_a_pdf_url_with_a_tracking_query_still_mines():
    # One real corpus URL arrived via a chatbot carrying ?utm_source=chatgpt.com.
    claims = mine(PDF_WITH_UTM)
    assert value(claims, "year") == "2025"
    assert value(claims, "track") == "Conference"


def test_claims_carry_the_url_as_evidence():
    assert all(c.evidence == ICLR for c in mine(ICLR))


def test_claims_are_tier_one_and_from_proceedings_url():
    for claim in mine(ICLR):
        assert claim.tier == 1
        assert claim.source == "proceedings_url"


def test_a_non_matching_host_yields_nothing():
    assert mine("https://openreview.net/forum?id=r0BFucF2dH") == []
    assert mine("https://arxiv.org/abs/2501.00001") == []
    assert mine("not a url at all") == []


def test_an_unrecognised_track_fails_loudly():
    # Defaulting to main track would silently misclassify a future track.
    bad = (
        "https://proceedings.neurips.cc/paper_files/paper/2027/hash/"
        "deadbeefdeadbeefdeadbeefdeadbeef-Abstract-Brand_New_Track.html"
    )
    with pytest.raises(UnknownTrack, match="Brand_New_Track"):
        mine(bad)


def test_a_matching_host_without_a_parseable_path_yields_nothing():
    assert mine("https://proceedings.neurips.cc/") == []
