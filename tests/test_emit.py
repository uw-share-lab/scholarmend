from __future__ import annotations

from pathlib import Path

from scholarmend.emit import project_ris, to_json
from scholarmend.ledger import Ledger
from scholarmend.models import Claim
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
    """Index-paired, not membership.

    `line in out.split("\\n")` would pass even if the projection reordered or
    duplicated lines, because it only asks whether each original line appears
    somewhere. The guarantee this module rests on is stronger: same lines, same
    order, same count, with only the corrected tags differing.

    This record already carries both PY and JF, so nothing is inserted into it
    and the index pairing holds exactly. Insertion is covered separately.
    """
    record, ledger = first()
    before = record.raw.split("\n")
    after = project_ris(record, ledger).split("\n")

    assert len(after) == len(before)
    for original, projected in zip(before, after):
        if original.startswith(("PY  - ", "JF  - ")):
            continue
        assert projected == original


def test_ris_projection_grows_by_exactly_the_number_of_inserted_tags():
    """Never delete, and insert only what was genuinely absent.

    The predecessor of this test asserted the line count never changed at all.
    That was wrong, and expensively so: 331 corpus records carry no PY line,
    so a projection that could only substitute silently dropped every year
    tier 2 resolved for them. The invariant is that the count rises by exactly
    the number of corrected tags the record did not already have, and never
    falls.
    """
    for record in parse_file(FIXTURE):
        ledger = resolve_record(record)
        out = project_ris(record, ledger)
        corrected = {
            tag
            for field, tag in (("year", "PY"), ("venue", "JF"))
            if (claim := ledger.resolve(field)) is not None and claim.source != "scholar"
        }
        inserted = sum(1 for tag in corrected if f"{tag}  - " not in record.raw)
        assert len(out.split("\n")) == len(record.raw.split("\n")) + inserted


def test_a_resolved_year_is_inserted_when_the_record_has_no_py_line():
    record = parse_file(FIXTURE)[2]  # openreview only: no PY line at all
    assert "PY  - " not in record.raw

    ledger = resolve_record(record)
    ledger.add(Claim(field="year", value="2025", source="openreview_api", tier=2,
                     confidence=0.99, evidence="venueid=ICLR.cc/2025/Conference"))
    out = project_ris(record, ledger)

    lines = out.split("\n")
    assert "PY  - 2025///" in lines
    assert len(lines) == len(record.raw.split("\n")) + 1
    # Immediately before ER, not appended after the record has ended.
    assert lines[lines.index("PY  - 2025///") + 1].startswith("ER  -")


def test_an_insertion_leaves_the_er_lines_trailing_space_intact():
    record = parse_file(FIXTURE)[2]
    ledger = resolve_record(record)
    ledger.add(Claim(field="year", value="2025", source="openreview_api", tier=2,
                     confidence=0.99, evidence="venueid=ICLR.cc/2025/Conference"))
    assert "ER  - \n" in project_ris(record, ledger)


def test_an_existing_py_line_is_substituted_rather_than_duplicated():
    record, ledger = first()
    out = project_ris(record, ledger)
    assert [line for line in out.split("\n") if line.startswith("PY  - ")] == ["PY  - 2025///"]


def test_a_record_with_no_er_line_still_gets_its_inserted_tag():
    """Malformed input must not crash, and must not lose the record.

    A false drop is silent and unrecoverable; an appended line at the end of a
    record that never terminated is neither.
    """
    from scholarmend.models import Record

    raw = "TY  - JOUR\nTI  - A record that never ended\n"
    record = Record(raw=raw, fields={"TY": ["JOUR"], "TI": ["A record that never ended"]},
                    source_file="broken.ris")
    ledger = Ledger()
    ledger.add(Claim(field="year", value="2025", source="openreview_api", tier=2,
                     confidence=0.99, evidence="venueid=ICLR.cc/2025/Conference"))

    out = project_ris(record, ledger)
    assert out == "TY  - JOUR\nTI  - A record that never ended\nPY  - 2025///\n"


def test_ris_projection_changes_only_py_jf_and_ab_lines():
    # Guards _TAG_FOR's scope from the outside: if a future change added AU to
    # it, this fails rather than silently altering author lines. The allowed
    # tags are written out here, not imported, for that reason. AB joined them
    # deliberately: it is one line per record, so it is substituted, never
    # restructured.
    #
    # Lines are aligned by diff, not by position. Pairing them with zip() made
    # every line after an inserted one compare against its neighbour, so on
    # any record with an insertion the test checked nothing (BACKLOG §4).
    import difflib

    allowed = {"PY", "JF", "AB"}
    cases = [(record, resolve_record(record)) for record in parse_file(FIXTURE)]
    # No fixture record needs an insertion offline, so add the one a tier-2
    # run makes: record 2 has no PY line. Non-Scholar authors and abstract
    # claims go in too -- without them, adding AU or AB to _TAG_FOR would
    # change no line here and this guard would pass by name only.
    record = parse_file(FIXTURE)[2]
    ledger = resolve_record(record)
    for field, value in (("year", "2025"), ("authors", "Someone Else"), ("abstract", "Other.")):
        ledger.add(Claim(field=field, value=value, source="openreview_api", tier=2,
                         confidence=0.99, evidence="venueid=ICLR.cc/2025/Conference"))
    cases.append((record, ledger))

    substituted = inserted = 0
    for record, ledger in cases:
        before = record.raw.split("\n")
        after = project_ris(record, ledger).split("\n")
        matcher = difflib.SequenceMatcher(None, before, after, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                continue
            assert op != "delete", f"projection deleted lines: {before[i1:i2]}"
            if op == "replace":
                # A substitution replaces a line with one of the same tag.
                assert i2 - i1 == j2 - j1, f"restructured: {before[i1:i2]} -> {after[j1:j2]}"
                for old, new in zip(before[i1:i2], after[j1:j2]):
                    assert old[:2] == new[:2] and old[:2] in allowed, (old, new)
                substituted += i2 - i1
            if op == "insert":
                assert {line[:2] for line in after[j1:j2]} <= allowed, after[j1:j2]
                inserted += j2 - j1
    # Both paths must actually be exercised, or this guards one of them by name only.
    assert substituted and inserted, (substituted, inserted)


def test_ris_projection_keeps_the_trailing_space_on_the_er_line():
    record, ledger = first()
    assert "ER  - \n" in project_ris(record, ledger)


def test_a_record_with_nothing_to_correct_round_trips_exactly():
    record = parse_file(FIXTURE)[2]  # openreview only, no miner claims
    assert project_ris(record, resolve_record(record)) == record.raw


def test_an_arxiv_only_records_identifier_survives_into_the_json():
    """The evidence a human adjudicating this record would need.

    arxiv_id is a key, not an answer: it never wins a field, so it has no entry
    in `fields`. It must still reach `claims`, because a record no resolver
    settled is exactly the one somebody has to look up by hand, and the id is
    what they would look it up with.
    """
    from scholarmend.models import Record

    raw = ("TY  - JOUR\n"
           "TI  - A preprint nobody has published yet\n"
           "UR  - https://arxiv.org/abs/2501.01234\n"
           "ER  - \n")
    record = Record(raw=raw, fields={"TY": ["JOUR"],
                                     "TI": ["A preprint nobody has published yet"],
                                     "UR": ["https://arxiv.org/abs/2501.01234"]},
                    source_file="preprints.ris")
    doc = to_json(record, resolve_record(record))

    identifiers = [c for c in doc["claims"] if c["field"] == "arxiv_id"]
    assert [c["value"] for c in identifiers] == ["2501.01234"]


def test_every_field_the_precedence_table_knows_can_reach_the_claims_array():
    # A hand-listed subset dropped pmlr_volume, pmc_id and arxiv_id silently.
    from scholarmend.ledger import PRECEDENCE

    record, ledger = first()
    for field in PRECEDENCE:
        ledger.add(Claim(field=field, value="x", source="scholar", tier=0,
                         confidence=0.1, evidence="e"))
    fields = {c["field"] for c in to_json(record, ledger)["claims"]}
    assert set(PRECEDENCE) <= fields, set(PRECEDENCE) - fields


def test_the_json_reports_a_resolved_venue_id():
    record, ledger = first()
    ledger.add(Claim(field="venue_id", value="ICLR.cc/2025/Conference",
                     source="openreview_api", tier=2, confidence=0.99, evidence="e"))
    assert to_json(record, ledger)["fields"]["venue_id"]["value"] == "ICLR.cc/2025/Conference"



def _with_snippet():
    """A record shaped like the real corpus: every one carries one AB snippet."""
    from scholarmend.models import Record

    raw = ("TY  - JOUR\n"
           "TI  - A paper\n"
           "AB  - … we observe that the benchmark metrics exhibit large …\n"
           "PY  - 2025///\n"
           "ER  - \n")
    fields = {"TY": ["JOUR"], "TI": ["A paper"],
              "AB": ["… we observe that the benchmark metrics exhibit large …"],
              "PY": ["2025///"], "ER": [""]}
    return Record(raw=raw, fields=fields, source_file="s.ris")


def test_a_recovered_abstract_replaces_the_snippet_on_its_own_line():
    record = _with_snippet()
    ledger = resolve_record(record)
    ledger.add(Claim(field="abstract", value="The full abstract.\nSecond  line.",
                     source="proceedings_page", tier=2, confidence=0.99, evidence="e"))
    out = project_ris(record, ledger)
    assert out == record.raw.replace(
        "AB  - … we observe that the benchmark metrics exhibit large …",
        "AB  - The full abstract. Second line.",
    )


def test_scholars_own_snippet_is_never_rewritten():
    record = _with_snippet()
    assert project_ris(record, resolve_record(record)) == record.raw
