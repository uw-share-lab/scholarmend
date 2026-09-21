"""Acceptance tests against the reviewers' hand-verified labels.

These are regression tests in the strongest sense available: the expected
values were produced by two people resolving records one at a time, with the
evidence for each recorded in ../Trust-Evals-LitReview/verification/.
"""

from __future__ import annotations

import csv
import glob
import json
from pathlib import Path

import pytest

from scholarmend import miners
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record
from scholarmend.resolvers.openreview import parse_venueid

GOLD = Path(__file__).parents[2] / "Trust-Evals-LitReview"
pytestmark = pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not alongside")


def corpus_records():
    for path in sorted(glob.glob(str(GOLD / "corpus" / "*.ris"))):
        yield from parse_file(Path(path))


def test_the_corpus_is_the_one_the_spec_measured():
    assert sum(1 for _ in corpus_records()) == 2413


def test_tier_one_leaves_exactly_seventeen_records_with_no_miner():
    """The true manual floor for this corpus.

    The spec quotes 21, measured before the PMC miner existed; PMC covers four
    of those, so the registry as built leaves 17. Changing this number means a
    miner was added or removed, which is worth noticing.
    """
    unmined = [r for r in corpus_records() if not miners.mine_all(r.urls)]
    assert len(unmined) == 17, len(unmined)


def test_proceedings_mining_covers_the_measured_1854():
    mined = [r for r in corpus_records()
             if any(c.field == "venue" for c in miners.mine_all(r.urls))]
    assert len(mined) == 1854, len(mined)


def test_scholar_loses_every_single_year_disagreement():
    """The spec's free property test. One loss here means precedence is wrong."""
    checked = disagreed = 0
    for record in corpus_records():
        ledger = resolve_record(record)
        winner = ledger.resolve("year")
        scholar = next((c for c in ledger.claims("year") if c.source == "scholar"), None)
        if winner is None or scholar is None:
            continue
        checked += 1
        if winner.value != scholar.value:
            disagreed += 1
            assert winner.source != "scholar", record.title
    assert disagreed == 1264, disagreed


def test_the_openreview_bucket_is_the_ninety_the_reviewers_resolved():
    labels = json.loads((GOLD / "verification" / "openreview-venues.json").read_text())
    assert len(labels) == 90
    for venueid in labels.values():
        claims = {c.field: c.value for c in parse_venueid(venueid)}
        assert claims.get("venue"), venueid
        assert claims.get("track"), venueid


def test_workshop_status_matches_every_reviewer_label():
    """Zero disagreements is the bar, not a high percentage."""
    labels = json.loads((GOLD / "verification" / "openreview-venues.json").read_text())
    resolutions = json.loads((GOLD / "verification" / "review-bucket-resolutions.json").read_text())
    truth = {r["forum"]: r["truth"] for r in resolutions if r.get("forum")}

    disagreements = []
    for forum_id, venueid in labels.items():
        if forum_id not in truth:
            continue
        claims = {c.field: c.value for c in parse_venueid(venueid)}
        predicted = "WORKSHOP" if "Workshop" in (claims.get("track") or "") else "MAIN"
        if predicted != truth[forum_id]:
            disagreements.append((forum_id, venueid, predicted, truth[forum_id]))
    assert disagreements == [], disagreements


def test_at_least_103_of_112_have_an_automated_resolution_path():
    """Reach, not correctness. The distinction matters, so it is in the name.

    What this measures is whether each labelled record has something for the
    pipeline to work with: a miner emitted a venue, or emitted a key some
    resolver consumes. It does not check that the resulting venue or year is
    right. A build in which every resolver returned garbage would still report
    104 of 112 here.

    Correctness is verified separately, and only for the 90 OpenReview records
    the reviewers hand-labelled: test_the_openreview_bucket_is_the_ninety_the
    _reviewers_resolved and test_workshop_status_matches_every_reviewer_label
    check those values against the labels. The remaining 14 are reached but
    unchecked -- no label exists for them, so nothing here asserts they came
    out right.

    It joins the labelled rows back to their real corpus records and asks the
    miners what they actually extract, rather than pattern-matching the
    publisher column -- a test that read the label to predict the answer would
    pass whether or not any code works.
    """
    import re

    resolutions = json.loads((GOLD / "verification" / "review-bucket-resolutions.json").read_text())
    assert len(resolutions) == 112

    def key(title):
        return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:60]

    by_title = {}
    for record in corpus_records():
        by_title.setdefault(key(record.title), []).append(record)

    # A key is only worth counting if a resolver exists that consumes it.
    RESOLVABLE_KEYS = {"forum_id", "pmlr_volume", "pmc_id"}

    settled, unmatched, stuck = 0, [], []
    for row in resolutions:
        records = by_title.get(key(row["title"]))
        if not records:
            unmatched.append(row["title"][:60])
            continue
        fields = set()
        for record in records:
            fields |= {c.field for c in miners.mine_all(record.urls)}
        if "venue" in fields or (fields & RESOLVABLE_KEYS):
            settled += 1
        else:
            stuck.append((row["title"][:55], row.get("pb")))

    assert not unmatched, f"could not join {len(unmatched)} labelled rows to the corpus: {unmatched[:3]}"
    assert settled >= 103, (
        f"only {settled} of 112 have a resolution path; still manual: {stuck}"
    )


def test_all_ten_hand_merged_titles_agree_on_year_after_resolution():
    """The secondary target: the hand-maintained merge list becomes unnecessary.

    Four collapse from tier-1 mining alone, because Scholar dated the copies
    2025 and 2026 while both URLs say 2025. The other six need the tier-2
    venueid to supply a year the OpenReview copy simply does not carry, so
    without credentials this asserts only the four.
    """
    listed = [r["title"].strip().lower()
              for r in csv.DictReader((GOLD / "verification" / "merge-titles-2026-09-20.csv").open())]
    assert len(listed) == 10

    by_title: dict[str, list] = {}
    for record in corpus_records():
        by_title.setdefault(record.title.strip().lower(), []).append(record)

    from scholarmend.emit import project_ris

    collapsed = 0
    for title in listed:
        copies = by_title.get(title, [])
        if len(copies) < 2:
            continue
        years, projections = set(), []
        for record in copies:
            ledger = resolve_record(record)
            claim = ledger.resolve("year")
            years.add(claim.value if claim else None)
            projections.append(project_ris(record, ledger))
        if len(years) == 1 and None not in years:
            collapsed += 1
            # The ledger agreeing is not the deliverable. Covidence and
            # venuetriage read only the RIS, so a year that agrees in the
            # ledger and is missing from the projection collapses nothing.
            # This assertion is the one that would have caught a projection
            # that could substitute a PY line but never insert one.
            year = next(iter(years))
            for projected in projections:
                assert f"PY  - {year}///" in projected, title
    assert collapsed >= 4, f"tier-1 mining collapsed only {collapsed} of the 10"


def test_no_record_is_ever_dropped():
    """The error asymmetry: a false drop is silent and unrecoverable."""
    from scholarmend.emit import project_ris

    count = 0
    for record in corpus_records():
        assert project_ris(record, resolve_record(record)).strip()
        count += 1
    assert count == 2413
