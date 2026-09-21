from __future__ import annotations

import json
import shutil
from pathlib import Path

from scholarmend.cli import main

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
