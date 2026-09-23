"""Acceptance tests against the reviewers' hand-verified labels.

These are regression tests in the strongest sense available: the expected
values were produced by two people resolving records one at a time, with the
evidence for each recorded in ../Trust-Evals-LitReview/verification/.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from scholarmend import miners
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record
from scholarmend.resolvers.openreview import parse_venueid

GOLD = Path(__file__).parents[2] / "Trust-Evals-LitReview"
pytestmark = pytest.mark.skipif(not GOLD.exists(), reason="validation corpus not alongside")


# The nine 2025-2026 exports the spec measured, named rather than globbed: the
# corpus directory has since grown (a 2020-2024 batch on 2026-09-23), and every
# number asserted below describes these nine files alone.
SPEC_CORPUS = (
    "ICLR.ris",
    "ICML.ris",
    "International Conference on Learning Representations.ris",
    "NeurIPS.ris",
    "PMLR.ris",
    "advances in neural information processing systems.ris",
    "international conference on machine learning.ris",
    "neural information processing systems.ris",
    "proceedings of machine learning research.ris",
)


def corpus_records():
    for name in SPEC_CORPUS:
        yield from parse_file(GOLD / "corpus" / name)


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


# --- ground truth beyond the OpenReview bucket -----------------------------
#
# The tests above verify the 90 records reached through an OpenReview venueid.
# The four below cover the routes that were reached but unchecked when this
# package first merged: the PMLR volumes, the PMC bridge, the verdict-flip
# record, and the per-record overrides. Together they take the number of
# hand-verified records the suite actually asserts from 90 to 103.
#
# Everything here runs offline from the committed cache. A lookup the cache
# lacks is itself a finding: the cache exists to back these claims.

OVERRIDES = GOLD / "verification" / "overrides-2026-09-20.csv"
DECISIONS = GOLD / "verification" / "decisions-2026-09-20.csv"
RESOLUTIONS = GOLD / "verification" / "review-bucket-resolutions.json"


def _cache():
    from scholarmend.cache import Cache

    return Cache(Path(__file__).parents[1] / ".scholarmend-cache", offline=True)


def _resolvers():
    from scholarmend.resolvers.openreview import OpenReviewResolver
    from scholarmend.resolvers.pmc import PmcResolver
    from scholarmend.resolvers.pmlr_index import PmlrIndexResolver

    cache = _cache()
    return {
        "openreview": OpenReviewResolver(cache),
        "pmlr_index": PmlrIndexResolver(cache),
        "pmc": PmcResolver(cache),
    }


def _normalise(title: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]", "", (title or "").lower())[:50]


def _by_title() -> dict[str, list]:
    index: dict[str, list] = {}
    for record in corpus_records():
        index.setdefault(_normalise(record.title), []).append(record)
    return index


def _resolve(record):
    """Resolve one record through the cache, degrading exactly as the CLI does."""
    from scholarmend.cache import CacheMiss
    from scholarmend.http import HttpError
    from scholarmend.resolvers.openreview import AuthError

    try:
        return resolve_record(record, **_resolvers())
    except (AuthError, CacheMiss, HttpError):
        return resolve_record(record)


def test_pmlr_volumes_match_the_reviewers_determinations():
    """The out-of-scope guard, checked against ground truth rather than itself.

    The reviewers recorded each PMLR volume's identity in `venue_true`, e.g.
    "PMLR v318 - Canadian Conference on AI". scholarmend must retrieve a
    proceedings title for the same volume AND decline to name a venue, because
    none of these is ICML, NeurIPS or ICLR. Coercing an unfamiliar conference
    onto a known one is how out-of-scope work gets screened in.
    """
    import re

    from scholarmend.resolvers.pmlr_index import venue_from_title

    rows = json.loads(RESOLUTIONS.read_text())
    index = _by_title()
    checked = []
    for row in rows:
        venue_true = row.get("venue_true") or ""
        match = re.search(r"PMLR v(\d+)", venue_true)
        if not match:
            continue
        volume = match.group(1)
        records = index.get(_normalise(row["title"]), [])
        assert records, f"{row['title'][:50]!r} did not join to the corpus"

        claims = {c.field: c.value for c in _resolvers()["pmlr_index"].resolve(volume)}
        assert claims, f"PMLR v{volume} is not in the committed cache"
        assert claims["venue_id"] == f"PMLR v{volume}"
        # Every PMLR volume the reviewers met was out of scope for this review.
        assert row["truth"] == "OUT_OF_SCOPE", row["truth"]
        assert claims.get("venue") is None, (
            f"v{volume} named {claims['venue']!r}; the reviewers ruled it out of scope"
        )
        title = (_cache().get(f"pmlr:volume:{volume}") or {}).get("title", "")
        assert venue_from_title(title) is None
        checked.append(volume)

    assert len(checked) == 10, checked
    assert set(checked) == {"310", "317", "318", "328"}, sorted(set(checked))


def test_the_pmc_bridge_reproduces_the_reviewers_override_decisions():
    """PMC id -> article volume -> PMLR index -> venue, against three rulings.

    The hardest path in the package, and the one the reviewers followed by hand:
    "PMC citation_volume 267 = PMLR v267 = ICML 2025". Note the asymmetry that
    matters - v267 is named ICML, while v287 (CHIL) and v297 (ML4H) have their
    titles retrieved and their venue deliberately left unnamed.
    """
    expected = {
        "PMC13004626": ("267", "ICML"),
        "PMC12477612": ("287", None),
        "PMC13322355": ("297", None),
    }
    resolvers = _resolvers()
    for pmc_id, (volume, venue) in expected.items():
        bridged = {c.field: c.value for c in resolvers["pmc"].resolve(pmc_id)}
        assert bridged.get("pmlr_volume") == volume, (pmc_id, bridged)

        claims = {c.field: c.value for c in resolvers["pmlr_index"].resolve(volume)}
        assert claims, f"PMLR v{volume} is not in the committed cache"
        assert claims.get("venue") == venue, (volume, claims.get("venue"), venue)
        assert claims["venue_id"] == f"PMLR v{volume}"


def test_no_verdict_flipped_without_a_recorded_reason():
    """The spec's third validation suite, which had no committed test.

    A flip is legitimate when the record was in the REVIEW bucket (its whole
    purpose was to be resolved by lookup) or when an override note records the
    evidence. A flip with neither is a verdict changed for no stated reason,
    which is exactly what an audit trail exists to make impossible.
    """
    rows = list(csv.DictReader(DECISIONS.open(encoding="utf-8-sig")))
    assert len(rows) == 1759, len(rows)

    flipped = [r for r in rows if r["verdict"] != r["final_verdict"]]
    assert len(flipped) == 112, len(flipped)

    unreasoned = [
        r for r in flipped
        if r["verdict"] != "REVIEW" and not (r["override_note"] or "").strip()
    ]
    assert unreasoned == [], [r["title"][:60] for r in unreasoned]


def test_every_override_is_either_reproduced_or_declared_unreachable():
    """The reviewers' ten per-record rulings, split honestly.

    Five have an automated route and scholarmend must reach the same venue the
    note records. Five do not - NSF landing pages, two Google Books chapters, a
    personal-page PDF - and the test asserts they resolve to NOTHING rather than
    quietly omitting them. That turns "we cannot check these" into a fact the
    suite states, and makes it fail the day a miner starts covering them, which
    would be news worth having.
    """
    index = _by_title()
    reachable, unreachable = [], []
    for row in csv.DictReader(OVERRIDES.open(encoding="utf-8-sig")):
        records = index.get(_normalise(row["title"]), [])
        assert records, f"override {row['title'][:50]!r} did not join to the corpus"

        fields: set[str] = set()
        for record in records:
            fields |= {c.field for c in miners.mine_all(record.urls)}
        keys = fields & {"venue", "forum_id", "pmlr_volume", "pmc_id"}
        (reachable if keys else unreachable).append((row, records))

    assert len(reachable) == 5, [r["title"][:40] for r, _ in reachable]
    assert len(unreachable) == 5, [r["title"][:40] for r, _ in unreachable]

    for row, records in reachable:
        # A venue claim always exists, because Scholar is the last resort in
        # PRECEDENCE. What matters is whether anything BETTER than Scholar
        # spoke. For an out-of-scope PMLR volume the answer is venue_id alone:
        # scholarmend retrieves the volume identity and deliberately declines
        # to name a venue, which is the behaviour under test.
        resolved = None
        for record in records:
            ledger = _resolve(record)
            for field in ("venue", "venue_id"):
                claim = ledger.resolve(field)
                if claim is not None and claim.source != "scholar":
                    resolved = claim
                    break
            if resolved is not None:
                break
        assert resolved is not None, (
            f"{row['title'][:50]!r} has a route but nothing beyond Scholar spoke"
        )
        # The resolved identity must be traceable in the reviewer's own note.
        note = (row["note"] or "").lower()
        value = resolved.value.lower()
        assert value in note or any(
            token in note for token in value.split() if len(token) > 3
        ), f"{row['title'][:40]!r}: resolved {resolved.value!r}, note says {row['note'][:80]!r}"

    for row, records in unreachable:
        for record in records:
            ledger = _resolve(record)
            for field in ("venue", "year", "track", "venue_id"):
                claim = ledger.resolve(field)
                assert claim is None or claim.source == "scholar", (
                    f"{row['title'][:40]!r} now resolves {field} from "
                    f"{claim.source!r} - a miner has started covering it, which "
                    f"is good news, but this test and the README must be updated"
                )
