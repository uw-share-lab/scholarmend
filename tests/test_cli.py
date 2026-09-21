from __future__ import annotations

import json
import shutil
from pathlib import Path

from scholarmend.cli import main
from scholarmend.resolvers.openreview import openreview_key

FIXTURE = Path(__file__).parent / "fixtures" / "sample.ris"


def setup_input(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    shutil.copy(FIXTURE, corpus / "sample.ris")
    return corpus


def run(tmp_path, corpus, out, *extra):
    """Run the CLI offline.

    Every test here runs with --offline. Without it the tier-2 and tier-3
    resolvers reach for the network on any record tier 1 could not settle, and
    tests/conftest.py rightly refuses. Offline is also the honest shape for a
    unit test: it exercises the degradation path a researcher hits on a train.
    """
    return main(["--input", str(corpus), "--out", str(out),
                 "--cache", str(tmp_path / "c"), "--offline", *extra])


def test_writes_both_outputs(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    # 1 rather than 0: offline with an empty cache is a PARTIAL run, and a
    # partial run must say so rather than looking successful.
    assert run(tmp_path, corpus, out) == 1
    assert (out / "resolved.json").exists()
    assert (out / "mended.ris").exists()


def test_the_json_has_one_object_per_record(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    assert len(json.loads((out / "resolved.json").read_text())) == 4


def test_the_ris_output_carries_the_corrected_year(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    assert "PY  - 2025///" in (out / "mended.ris").read_text(encoding="utf-8")


def test_a_report_lists_what_stayed_unresolved(tmp_path):
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    report = (out / "report.txt").read_text()
    assert "unresolved" in report.lower()


def test_offline_without_a_cache_still_completes_on_tier_one(tmp_path):
    # Offline must not crash: tier-1 mining needs no network at all.
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    # A CacheMiss must degrade this record, not abort the other 2,412.
    assert run(tmp_path, corpus, out) == 1
    assert (out / "mended.ris").exists()
    assert "PY  - 2025///" in (out / "mended.ris").read_text(encoding="utf-8")


def test_an_empty_input_directory_is_an_error_not_a_silent_success(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    out = tmp_path / "o"

    assert run(tmp_path, empty, out) == 2

    # The name of this test is the assertion that matters. A run that wrote
    # empty outputs and then returned 2 would be a silent success wearing an
    # error code: a later step reading mended.ris would see a valid, empty
    # corpus. The early return must happen before anything is created.
    assert not out.exists(), sorted(p.name for p in out.iterdir())


def test_running_twice_produces_identical_output(tmp_path):
    corpus = setup_input(tmp_path)
    for name in ("a", "b"):
        run(tmp_path, corpus, tmp_path / name)
    assert (tmp_path / "a" / "mended.ris").read_bytes() == (tmp_path / "b" / "mended.ris").read_bytes()
    assert (tmp_path / "a" / "resolved.json").read_bytes() == (tmp_path / "b" / "resolved.json").read_bytes()


def test_a_warm_cache_resolves_tier_two_without_credentials_or_network(tmp_path, monkeypatch):
    """The reproducibility path, which is the one a third party runs.

    Someone who clones the repository has the committed cache and no OpenReview
    account. They run without --offline, because nothing told them to. Tier 2
    must answer from the cache anyway, and must not call the API -- neither for
    a lookup nor for a login. conftest's guard fails this test if it does.
    """
    from scholarmend.cache import Cache

    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_USER", raising=False)
    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_PASSWORD", raising=False)

    corpus = setup_input(tmp_path)
    cache_dir = tmp_path / "warm"
    # r0BFucF2dH is the forum id on the third fixture record, which carries no
    # PY line and no resolvable venue without tier 2.
    Cache(cache_dir).put(openreview_key("r0BFucF2dH"), {"venueid": "ICLR.cc/2025/Conference"})

    out = tmp_path / "out"
    code = main(["--input", str(corpus), "--out", str(out), "--cache", str(cache_dir)])

    documents = json.loads((out / "resolved.json").read_text())
    resolved = next(d for d in documents if d["title"].startswith("Meta-Router"))
    assert resolved["fields"]["venue"]["value"] == "ICLR"
    assert resolved["fields"]["year"]["value"] == "2025"
    assert resolved["fields"]["venue"]["source"] == "openreview_api"
    # The cache answered every lookup, so nothing degraded.
    assert code == 0

    # And the answer reaches the artifact Covidence actually reads.
    assert "PY  - 2025///" in (out / "mended.ris").read_text(encoding="utf-8-sig")


def test_without_credentials_the_message_does_not_claim_tier_two_is_disabled(
    tmp_path, monkeypatch, capsys
):
    from scholarmend.cache import Cache

    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_USER", raising=False)
    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_PASSWORD", raising=False)

    corpus = setup_input(tmp_path)
    cache_dir = tmp_path / "warm"
    Cache(cache_dir).put(openreview_key("r0BFucF2dH"), {"venueid": "ICLR.cc/2025/Conference"})

    main(["--input", str(corpus), "--out", str(tmp_path / "out"), "--cache", str(cache_dir)])
    assert "tier 2 disabled" not in capsys.readouterr().err


def test_the_ris_output_keeps_the_bom_so_the_file_round_trips(tmp_path):
    # parse_file reads utf-8-sig; writing plain utf-8 dropped the BOM, so the
    # corpus round-tripped record by record but not as a file.
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    assert (out / "mended.ris").read_bytes().startswith(b"\xef\xbb\xbf")


def test_the_report_omits_a_field_no_source_in_this_run_could_supply(tmp_path):
    """doi accused every record of a failure no human could act on.

    Nothing in the offline run resolves a doi for any record, so listing it
    against all of them buried the genuinely unresolved venues and years.
    """
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    report = (out / "report.txt").read_text()

    listing = [line for line in report.splitlines() if line.startswith("  unresolved")]
    assert not any("doi" in line for line in listing), listing
    assert "no source in this run could supply" in report
    assert "doi" in report  # named once, rather than silently dropped


def test_the_report_still_names_a_record_whose_year_is_unresolved(tmp_path):
    # The openreview-only record cannot be settled offline with an empty cache,
    # and it is exactly the kind of record the report exists to surface.
    corpus = setup_input(tmp_path)
    out = tmp_path / "out"
    run(tmp_path, corpus, out)
    listing = [line for line in (out / "report.txt").read_text().splitlines()
               if line.startswith("  unresolved")]
    assert any("Meta-Router" in line and "year" in line for line in listing), listing


def test_the_report_lists_missing_venues_and_years_before_anything_else():
    """The 200-line cap must not be able to hide the deliverable.

    Sorting is what makes the truncation safe: a record missing a venue or a
    year is what a human has to act on, so it cannot be pushed off the end by
    records missing only a track.
    """
    from scholarmend.cli import _report

    def document(**values):
        return {"fields": {field: {"value": values.get(field)}
                           for field in ("venue", "year", "track", "version",
                                         "authors", "abstract", "doi", "venue_id")}}

    documents = [document(venue="ICLR", year="2025", track="Conference", version="proceedings",
                          authors="A", abstract="x", doi="10.1/x", venue_id="ICLR.cc/2025/Conference")]
    unresolved = [("Only a track missing", ["track"]), ("A year missing", ["year"])]

    listing = [line for line in _report(documents, unresolved).splitlines()
               if line.startswith("  unresolved")]
    assert len(listing) == 2, listing
    assert "A year missing" in listing[0]
    assert "Only a track missing" in listing[1]
