"""scripts/repopulate.py must never cost the committed cache an entry.

It used to delete every poisoned entry up front and then refetch with an
unguarded loop, so a run without credentials or with the network down deleted
~29 entries and restored none (BACKLOG §3). The cache is the artifact behind
the reproducibility claim; losing entries from it silently is the failure.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from scholarmend.cache import Cache
from scholarmend.http import HttpError
from scholarmend.resolvers.openreview import AuthError

SCRIPT = Path(__file__).parents[1] / "scripts" / "repopulate.py"
spec = importlib.util.spec_from_file_location("repopulate", SCRIPT)
repopulate = importlib.util.module_from_spec(spec)
sys.modules["repopulate"] = repopulate  # @dataclass resolves its module here
spec.loader.exec_module(repopulate)

OR = "openreview:note:"
PM = "pmlr:volume:"


def seeded(tmp_path):
    cache = Cache(tmp_path)
    cache.put(OR + "empty1", {})
    cache.put(OR + "empty2", {})
    cache.put(PM + "300", {"title": ""})
    cache.put(OR + "good", {"venueid": "ICML.cc/2025/Conference"})
    return cache


def snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text(encoding="utf-8")
            for p in sorted(root.glob("*/*.json"))}


def resolver(cache, prefix, loader):
    return lambda ident: cache.fetch(prefix + ident, lambda: loader(ident))


def failing(error):
    def loader(_ident):
        raise error
    return loader


@pytest.mark.parametrize("error", [
    AuthError("no credentials"),
    HttpError("503 from api"),
    OSError("network is unreachable"),
])
def test_a_failed_refetch_leaves_the_cache_exactly_as_it_was(tmp_path, error):
    cache = seeded(tmp_path)
    before = snapshot(tmp_path)
    result = repopulate.repopulate(
        cache, resolver(cache, OR, failing(error)), resolver(cache, PM, failing(error)), delay=0
    )
    assert snapshot(tmp_path) == before
    assert result.failed == 3 and result.recovered == 0


def test_an_interrupted_run_restores_the_entry_it_was_working_on(tmp_path):
    cache = seeded(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(KeyboardInterrupt):
        repopulate.repopulate(
            cache, resolver(cache, OR, failing(KeyboardInterrupt())),
            resolver(cache, PM, failing(KeyboardInterrupt())), delay=0,
        )
    assert snapshot(tmp_path) == before
    assert not list(tmp_path.glob("*/*.aside")), "no stray set-aside files"


def test_a_successful_refetch_replaces_only_the_poisoned_entries(tmp_path):
    cache = seeded(tmp_path)
    good_before = cache.get(OR + "good")
    result = repopulate.repopulate(
        cache,
        resolver(cache, OR, lambda f: {"venueid": f"ICLR.cc/2025/{f}"}),
        resolver(cache, PM, lambda v: {"title": f"Volume {v}"}),
        delay=0,
    )
    assert cache.get(OR + "empty1") == {"venueid": "ICLR.cc/2025/empty1"}
    assert cache.get(PM + "300") == {"title": "Volume 300"}
    assert cache.get(OR + "good") == good_before
    assert (result.recovered, result.failed, result.still_empty) == (3, 0, 0)
    assert not list(tmp_path.glob("*/*.aside"))


def test_one_failure_does_not_stop_the_rest(tmp_path):
    cache = seeded(tmp_path)

    def flaky(forum):
        if forum == "empty1":
            raise HttpError("429")
        return {"venueid": "ICML.cc/2025/Conference"}

    result = repopulate.repopulate(
        cache, resolver(cache, OR, flaky), resolver(cache, PM, lambda v: {"title": "T"}), delay=0
    )
    assert cache.get(OR + "empty1") == {}  # kept, not lost
    assert cache.get(OR + "empty2") == {"venueid": "ICML.cc/2025/Conference"}
    assert (result.recovered, result.failed) == (2, 1)


def test_a_still_empty_answer_is_counted_not_hidden(tmp_path):
    cache = seeded(tmp_path)
    result = repopulate.repopulate(
        cache, resolver(cache, OR, lambda f: {}), resolver(cache, PM, lambda v: {"title": ""}),
        delay=0,
    )
    assert (result.recovered, result.failed, result.still_empty) == (0, 0, 3)
    assert cache.get(OR + "empty1") == {}


def test_main_without_credentials_skips_openreview_and_touches_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_USER", raising=False)
    monkeypatch.delenv("SCHOLARMEND_OPENREVIEW_PASSWORD", raising=False)
    seeded(tmp_path)
    before = snapshot(tmp_path)
    # The PMLR lookup hits the suite's network guard (AssertionError), which
    # is not a lookup failure; stub the resolver so only the OpenReview
    # path is under test here.
    monkeypatch.setattr(repopulate, "PmlrIndexResolver",
                        lambda cache: type("R", (), {"resolve": lambda self, v: None})())
    assert repopulate.main(["--cache", str(tmp_path), "--delay", "0"]) == 0
    assert snapshot(tmp_path) == before
