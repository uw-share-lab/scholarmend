from __future__ import annotations

import pytest

from scholarmend.cache import Cache
from scholarmend.resolvers.openreview import (
    OpenReviewResolver,
    openreview_key,
    parse_venueid,
)


def value(claims, field):
    return next((c.value for c in claims if c.field == field), None)


def test_a_conference_venueid_is_main_track():
    claims = parse_venueid("ICML.cc/2025/Conference")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "year") == "2025"
    assert value(claims, "track") == "Conference"
    assert value(claims, "version") == "proceedings"


def test_a_workshop_venueid_names_the_workshop():
    claims = parse_venueid("ICML.cc/2026/Workshop/AI4GOOD")
    assert value(claims, "venue") == "ICML"
    assert value(claims, "year") == "2026"
    assert value(claims, "track") == "Workshop/AI4GOOD"


def test_a_neurips_regional_workshop_is_still_a_workshop():
    # Real value from the corpus: NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM
    claims = parse_venueid("NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM")
    assert value(claims, "venue") == "NeurIPS"
    assert value(claims, "track") == "Workshop_Mexico_City/ResponsibleFM"


def test_a_non_iclr_venueid_keeps_its_own_organisation():
    claims = parse_venueid("AAAI.org/2026/Workshop/AIGOV/Submission")
    assert value(claims, "venue") == "AAAI"


@pytest.mark.parametrize("venueid", [
    "ICLR.cc/2025/Conference/Submission",  # under review, or never accepted
    "ICLR.cc/2025/Conference/Rejected_Submission",
    "ICLR.cc/2025/Conference/Withdrawn_Submission",
    "ICLR.cc/2025/Conference/Desk_Rejected_Submission",
    "AAAI.org/2026/Workshop/AIGOV/Submission",
])
def test_a_submission_venueid_is_not_reported_as_proceedings(venueid):
    """OpenReview gives an accepted paper the bare venue (…/Conference) and
    keeps a *Submission suffix on everything else. The suffix used to be
    stripped as routing detail, which turned an unaccepted submission into
    track=Conference, version=proceedings. BACKLOG §8."""
    claims = parse_venueid(venueid)
    assert value(claims, "version") is None
    assert value(claims, "track") == venueid.split("/", 2)[2]  # verbatim


def test_a_submission_venueid_still_says_where_and_when_it_was_submitted():
    claims = parse_venueid("ICLR.cc/2025/Conference/Rejected_Submission")
    assert (value(claims, "venue"), value(claims, "year")) == ("ICLR", "2025")


@pytest.mark.parametrize("venueid", [
    "ICML.cc/2025/Conference",
    "ICML.cc/2025/Position_Paper_Track",
    "ICML.cc/2026/Workshop/AI4GOOD",
])
def test_a_published_venueid_is_still_proceedings(venueid):
    assert value(parse_venueid(venueid), "version") == "proceedings"


def test_a_track_without_a_submission_suffix_is_left_alone():
    assert value(parse_venueid("ICML.cc/2026/Workshop/AI4GOOD"), "track") == "Workshop/AI4GOOD"


def test_the_venueid_itself_is_retained_as_a_claim():
    assert value(parse_venueid("ICML.cc/2025/Conference"), "venue_id") == "ICML.cc/2025/Conference"


def test_an_unparseable_venueid_yields_only_the_raw_id():
    claims = parse_venueid("something-odd")
    assert value(claims, "venue_id") == "something-odd"
    assert value(claims, "venue") is None


def test_claims_are_tier_two():
    assert all(c.tier == 2 for c in parse_venueid("ICML.cc/2025/Conference"))


def fake_api(monkeypatch, notes):
    """Stand in for scholarmend.http.get_json; records the URLs asked for."""
    asked = []

    def get_json(url, headers=None):
        asked.append(url)
        return {"notes": notes}

    monkeypatch.setattr("scholarmend.http.get_json", get_json)
    return asked


def test_the_loader_asks_for_the_submission_note_itself(tmp_path, monkeypatch):
    """`?forum=…&limit=1` returned an arbitrary note -- a Decision note on 25 of
    96 real forums -- and the venue was then derived from its invitation,
    which every paper at a conference has, accepted or not. Verified live
    2026-09-21: rejected ICLR 2025 paper zkNCWtw2fd came out as
    ICLR.cc/2025/Conference, proceedings. In API v2 the forum id is the
    submission note's id, so ask for that note. BACKLOG §9."""
    asked = fake_api(monkeypatch, [{"id": "F1", "content": {"venueid": {"value": "ICLR.cc/2025/Conference"}}}])
    OpenReviewResolver(Cache(tmp_path), token="t").resolve("F1")
    assert asked == ["https://api2.openreview.net/notes?id=F1"]


def test_a_rejected_submission_is_recorded_as_rejected(tmp_path, monkeypatch):
    fake_api(monkeypatch, [{"id": "zkNCWtw2fd",
                            "content": {"venueid": {"value": "ICLR.cc/2025/Conference/Rejected_Submission"}}}])
    claims = OpenReviewResolver(Cache(tmp_path), token="t").resolve("zkNCWtw2fd")
    assert value(claims, "track") == "Conference/Rejected_Submission"
    assert value(claims, "version") is None


@pytest.mark.parametrize("notes", [
    [],                                                        # no such note
    [{"id": "F1", "content": {}}],                             # no venueid
    [{"id": "F1", "invitations": ["ICLR.cc/2025/Conference/Submission9/-/Decision"]}],
    [{"id": "OTHER", "content": {"venueid": {"value": "ICLR.cc/2025/Conference"}}}],
])
def test_a_note_that_does_not_state_its_own_venueid_records_nothing(tmp_path, monkeypatch, notes):
    """Nothing is derived. An unresolved venue goes to a human; a guessed one does not."""
    fake_api(monkeypatch, notes)
    cache = Cache(tmp_path)
    assert OpenReviewResolver(cache, token="t").resolve("F1") == []
    assert cache.get(openreview_key("F1")) == {}


def test_the_cache_key_is_new_so_derived_entries_cannot_mix_with_direct_ones():
    """Entries under the old openreview:notes: prefix may hold a derived venueid
    and cannot be told apart; nothing reads that prefix any more."""
    assert openreview_key("F1") == "openreview:note:F1"


def test_resolve_serves_a_cached_forum_without_network(tmp_path):
    cache = Cache(tmp_path)
    cache.put(openreview_key("XYZ"), {"venueid": "ICLR.cc/2026/Conference"})
    resolver = OpenReviewResolver(cache=cache, token=None)
    # token is None, so any network attempt would raise; a cache hit must not.
    assert value(resolver.resolve("XYZ"), "venue") == "ICLR"


def test_resolve_in_offline_mode_raises_on_a_miss(tmp_path):
    import pytest

    from scholarmend.cache import CacheMiss

    resolver = OpenReviewResolver(cache=Cache(tmp_path, offline=True), token="t")
    with pytest.raises(CacheMiss):
        resolver.resolve("NEVER_SEEN")


def test_resolve_without_a_token_refuses_rather_than_calling_anonymously(tmp_path):
    import pytest

    from scholarmend.resolvers.openreview import AuthError

    resolver = OpenReviewResolver(cache=Cache(tmp_path), token=None)
    with pytest.raises(AuthError, match="credentials"):
        resolver.resolve("NOT_CACHED")


import json
from pathlib import Path

import pytest

GOLD = Path(__file__).parents[2] / "Trust-Evals-LitReview" / "verification" / "openreview-venues.json"


@pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not checked out alongside")
def test_every_verified_venueid_parses_into_a_venue_and_a_workshop_verdict():
    venues = json.loads(GOLD.read_text())
    assert len(venues) == 90
    for forum_id, venueid in venues.items():
        claims = parse_venueid(venueid)
        got = {c.field: c.value for c in claims}
        assert got.get("venue"), f"{forum_id}: no venue from {venueid!r}"
        assert got.get("year"), f"{forum_id}: no year from {venueid!r}"
        assert got.get("track"), f"{forum_id}: no track from {venueid!r}"


RESOLUTIONS = (
    Path(__file__).parents[2] / "Trust-Evals-LitReview" / "verification"
    / "review-bucket-resolutions.json"
)


def _predict(venueid: str) -> str:
    """The binary rule the classifier actually uses.

    Deliberately NOT ``endswith("/Conference")``. OpenReview carries the same
    track diversity the proceedings URLs do -- ICML.cc/2025/Position_Paper_Track
    is main track, and the reviewers labelled it MAIN -- so anything that is not
    a workshop is main track. Counting only ``/Conference`` would drop that
    record, which is the false-drop direction the design calls silent and
    unrecoverable.
    """
    return "WORKSHOP" if "Workshop" in venueid else "MAIN"


@pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not checked out alongside")
def test_workshop_detection_matches_the_reviewers_labels():
    venues = json.loads(GOLD.read_text())
    predicted = [_predict(v) for v in venues.values()]
    assert predicted.count("WORKSHOP") == 73, predicted.count("WORKSHOP")
    assert predicted.count("MAIN") == 17, predicted.count("MAIN")


@pytest.mark.skipif(
    not (GOLD.exists() and RESOLUTIONS.exists()),
    reason="validation corpus not checked out alongside",
)
def test_no_venueid_prediction_disagrees_with_a_reviewer_label():
    """Per-record agreement, which aggregate counts cannot prove.

    Two wrong predictions in opposite directions still sum to 73/17, so the
    counts above are necessary but not sufficient. This asserts the stronger
    claim the acceptance criterion actually rests on: zero disagreements.
    """
    venues = json.loads(GOLD.read_text())
    truth = {
        row["forum"]: row["truth"]
        for row in json.loads(RESOLUTIONS.read_text())
        if row.get("forum")
    }
    disagreements = [
        (forum, venueid, _predict(venueid), truth[forum])
        for forum, venueid in venues.items()
        if forum in truth and _predict(venueid) != truth[forum]
    ]
    assert disagreements == [], disagreements
