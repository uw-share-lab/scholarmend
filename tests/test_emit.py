from __future__ import annotations

from pathlib import Path

from scholarmend.emit import project_ris, to_json
from scholarmend.parse import parse_file
from scholarmend.pipeline import resolve_record

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def first():
    record = parse_file(FIXTURE)[0]
    return record, resolve_record(record)


def test_json_reports_the_winning_value_with_its_source():
    record, ledger = first()
    doc = to_json(record, ledger)
    assert doc["fields"]["year"]["value"] == "2025"
    assert doc["fields"]["year"]["source"] == "proceedings_url"


def test_json_retains_the_losing_scholar_claim():
    record, ledger = first()
    doc = to_json(record, ledger)
    losers = [c for c in doc["claims"] if c["field"] == "year" and c["source"] == "scholar"]
    assert losers and losers[0]["value"] == "2026"


def test_json_marks_an_unresolved_field():
    record = parse_file(FIXTURE)[2]
    doc = to_json(record, resolve_record(record))
    assert doc["fields"]["track"]["unresolved"] is True


def test_json_carries_the_title_and_source_file():
    record, ledger = first()
    doc = to_json(record, ledger)
    assert doc["title"].startswith("Thinkbench")
    assert doc["source_file"] == "sample.ris"


def test_ris_projection_corrects_the_year_in_place():
    record, ledger = first()
    assert "PY  - 2025///" in project_ris(record, ledger)
    assert "PY  - 2026///" not in project_ris(record, ledger)


def test_ris_projection_preserves_scholars_trailing_slash_convention():
    record, ledger = first()
    # Covidence and venuetriage both parse PY; keep the shape Scholar writes.
    assert "PY  - 2025///" in project_ris(record, ledger)


def test_ris_projection_corrects_the_ellipsized_venue():
    record, ledger = first()
    out = project_ris(record, ledger)
    assert "JF  - NeurIPS" in out
    assert "… Neural Information …" not in out


def test_ris_projection_leaves_every_untouched_line_byte_identical():
    record, ledger = first()
    out = project_ris(record, ledger)
    untouched = [ln for ln in record.raw.split("\n") if not ln.startswith(("PY  - ", "JF  - "))]
    for line in untouched:
        assert line in out.split("\n")


def test_ris_projection_keeps_the_trailing_space_on_the_er_line():
    record, ledger = first()
    assert "ER  - \n" in project_ris(record, ledger)


def test_a_record_with_nothing_to_correct_round_trips_exactly():
    record = parse_file(FIXTURE)[2]  # openreview only, no miner claims
    assert project_ris(record, resolve_record(record)) == record.raw
