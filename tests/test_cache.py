from __future__ import annotations

from typing import ClassVar

import pytest

from scholarmend.cache import Cache, CacheMiss


def test_a_put_value_comes_back(tmp_path):
    cache = Cache(tmp_path)
    cache.put("openreview:abc", {"venueid": "ICML.cc/2025/Conference"})
    assert cache.get("openreview:abc") == {"venueid": "ICML.cc/2025/Conference"}


def test_a_missing_key_is_none(tmp_path):
    assert Cache(tmp_path).get("nope") is None


def test_fetch_calls_the_loader_once_then_serves_from_disk(tmp_path):
    calls = []

    def loader():
        calls.append(1)
        return {"v": 1}

    cache = Cache(tmp_path)
    assert cache.fetch("k", loader) == {"v": 1}
    assert cache.fetch("k", loader) == {"v": 1}
    assert len(calls) == 1


def test_a_second_cache_object_sees_the_first_ones_writes(tmp_path):
    Cache(tmp_path).put("k", {"v": 2})
    assert Cache(tmp_path).get("k") == {"v": 2}


def test_offline_mode_refuses_to_call_the_loader(tmp_path):
    def loader():
        raise AssertionError("the network must not be touched in offline mode")

    with pytest.raises(CacheMiss, match="k"):
        Cache(tmp_path, offline=True).fetch("k", loader)


def test_offline_mode_still_serves_what_is_cached(tmp_path):
    Cache(tmp_path).put("k", {"v": 3})

    def loader():
        raise AssertionError("must not be called")

    assert Cache(tmp_path, offline=True).fetch("k", loader) == {"v": 3}


def test_keys_with_awkward_characters_are_safe_on_disk(tmp_path):
    cache = Cache(tmp_path)
    key = "s2:Attention Is All You Need?/\\:*"
    cache.put(key, {"ok": True})
    assert cache.get(key) == {"ok": True}


def test_rate_limit_pause_is_skipped_while_budget_remains():
    from scholarmend.http import _respect_rate_limit

    class Response:
        headers: ClassVar[dict[str, str]] = {"ratelimit-remaining": "497", "ratelimit-reset": "3400"}

    slept = []
    _respect_rate_limit(Response(), sleep=slept.append)
    assert slept == []


def test_rate_limit_pause_waits_for_the_window_when_budget_is_spent():
    # OpenReview allows 500 requests an hour; tier 2 needs 527, so the run
    # must wait out the window rather than fail 27 calls from the end.
    from scholarmend.http import _respect_rate_limit

    class Response:
        headers: ClassVar[dict[str, str]] = {"ratelimit-remaining": "0", "ratelimit-reset": "120"}

    slept = []
    _respect_rate_limit(Response(), sleep=slept.append)
    assert slept and 120 <= slept[0] <= 122


def test_rate_limit_wait_is_capped_against_a_hostile_header():
    from scholarmend.http import MAX_RATELIMIT_WAIT, _respect_rate_limit

    class Response:
        headers: ClassVar[dict[str, str]] = {"ratelimit-remaining": "0", "ratelimit-reset": "999999"}

    slept = []
    _respect_rate_limit(Response(), sleep=slept.append)
    assert slept[0] <= MAX_RATELIMIT_WAIT + 1


def test_missing_rate_limit_headers_are_simply_ignored():
    from scholarmend.http import _respect_rate_limit

    class Response:
        headers: ClassVar[dict[str, str]] = {}

    slept = []
    _respect_rate_limit(Response(), sleep=slept.append)
    assert slept == []


def test_stored_files_are_readable_json_for_auditing(tmp_path):
    import json

    cache = Cache(tmp_path)
    cache.put("k", {"v": 4})
    path = next(tmp_path.rglob("*.json"))
    assert json.loads(path.read_text())["payload"] == {"v": 4}
    assert json.loads(path.read_text())["key"] == "k"
