from __future__ import annotations

from pathlib import Path

import pytest

from scholarmend.parse import emit_ris, parse_file, parse_ris

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def test_parses_every_record():
    records = parse_file(FIXTURE)
    assert len(records) == 4


def test_round_trip_is_byte_identical():
    text = FIXTURE.read_text(encoding="utf-8-sig")
    assert emit_ris(parse_ris(text, "sample.ris")) == text


def test_fixture_retains_the_trailing_space_on_er_lines():
    # The real corpus writes "ER  - " with a trailing space. A fixture that
    # loses it makes the round-trip test pass without proving anything.
    raw = FIXTURE.read_bytes().decode("utf-8-sig")
    assert "ER  - \n" in raw


def test_fixture_retains_the_utm_query_string():
    # One real URL arrived via a chatbot and carries a tracking parameter.
    raw = FIXTURE.read_bytes().decode("utf-8-sig")
    assert "?utm_source=chatgpt.com" in raw


def test_fixture_is_saved_with_a_bom():
    assert FIXTURE.read_bytes().startswith(b"\xef\xbb\xbf")


def test_repeated_tags_keep_every_value_in_order():
    first = parse_file(FIXTURE)[0]
    assert first.fields["AU"] == ["Huang, S", "Yang, L", "..."]


def test_year_strips_scholars_trailing_slashes():
    assert parse_file(FIXTURE)[0].year == "2026"


def test_urls_returns_every_ur_value():
    third = parse_file(FIXTURE)[2]
    assert third.urls == ["https://openreview.net/forum?id=r0BFucF2dH"]


def test_a_record_with_no_year_reports_empty_string():
    assert parse_file(FIXTURE)[2].year == ""


def test_content_before_the_first_record_is_refused():
    with pytest.raises(ValueError, match="content before the first record"):
        parse_ris("junk\nTY  - JOUR\nER  - \n", "bad.ris")


def test_record_is_deliberately_unhashable():
    # Record holds a mutable fields view. frozen=True would otherwise
    # auto-generate a __hash__ that raises a confusing "unhashable type: dict".
    record = parse_file(FIXTURE)[0]
    with pytest.raises(TypeError, match="unhashable type: 'Record'"):
        hash(record)


def test_records_still_compare_by_value():
    a, b = parse_file(FIXTURE)[0], parse_file(FIXTURE)[0]
    assert a == b


def test_a_file_with_content_but_no_ty_line_is_refused():
    # The false-drop direction: returning [] here made a whole file vanish with
    # no error, and nothing downstream could tell that apart from an empty one.
    with pytest.raises(ValueError, match="no 'TY  - ' line"):
        parse_ris("AU  - Someone\nTI  - Not actually a record\n", "headerless.ris")


def test_a_blank_file_is_still_simply_empty():
    assert parse_ris("", "empty.ris") == []
    assert parse_ris("\n  \n", "blank.ris") == []
