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


def _raise_429(headers: dict[str, str]):
    """A urlopen replacement that answers 429 with the given headers."""
    import email.message
    import urllib.error

    message = email.message.Message()
    for name, value in headers.items():
        message[name] = value

    def urlopen(*args, **kwargs):
        raise urllib.error.HTTPError("https://example.test/x", 429, "Too Many", message, None)

    return urlopen


def test_a_429_waits_for_the_window_the_server_advertises(monkeypatch):
    # The failure this replaces: a real 429 slept 1s then 2s and gave up, while
    # OpenReview's hour-wide window still had fifty minutes left on it.
    import urllib.request

    from scholarmend.http import HttpError, get_json

    monkeypatch.setattr(urllib.request, "urlopen", _raise_429({"ratelimit-reset": "300"}))
    slept: list[float] = []
    with pytest.raises(HttpError):
        get_json("https://example.test/x", sleep=slept.append)
    assert slept and all(300 <= s <= 302 for s in slept), slept


def test_a_429_honours_retry_after_when_that_is_what_the_server_sends(monkeypatch):
    import urllib.request

    from scholarmend.http import HttpError, get_json

    monkeypatch.setattr(urllib.request, "urlopen", _raise_429({"retry-after": "90"}))
    slept: list[float] = []
    with pytest.raises(HttpError):
        get_json("https://example.test/x", sleep=slept.append)
    assert slept and all(90 <= s <= 92 for s in slept), slept


def test_a_429_with_no_headers_falls_back_to_exponential_backoff(monkeypatch):
    import urllib.request

    from scholarmend.http import HttpError, get_json

    monkeypatch.setattr(urllib.request, "urlopen", _raise_429({}))
    slept: list[float] = []
    with pytest.raises(HttpError):
        get_json("https://example.test/x", sleep=slept.append)
    assert slept == [1.0, 2.0], slept


def test_a_429_wait_is_capped_against_a_hostile_header(monkeypatch):
    import urllib.request

    from scholarmend.http import MAX_RATELIMIT_WAIT, HttpError, get_json

    monkeypatch.setattr(urllib.request, "urlopen", _raise_429({"ratelimit-reset": "999999"}))
    slept: list[float] = []
    with pytest.raises(HttpError):
        get_json("https://example.test/x", sleep=slept.append)
    assert all(s <= MAX_RATELIMIT_WAIT + 1 for s in slept), slept


def test_a_truncated_cache_file_is_reported_and_treated_as_a_miss(tmp_path, capsys):
    """An interrupted run used to poison the next one.

    write_text is not atomic, so a run killed mid-write left half a JSON
    document behind and the next get() raised JSONDecodeError from inside the
    resolver. A damaged entry must cost one lookup, not the run.
    """
    cache = Cache(tmp_path)
    cache.put("k", {"v": 5})
    path = next(tmp_path.rglob("*.json"))
    path.write_text('{"key": "k", "payl', encoding="utf-8")

    assert cache.get("k") is None
    assert "unreadable" in capsys.readouterr().err

    assert cache.fetch("k", lambda: {"v": 6}) == {"v": 6}
    assert cache.get("k") == {"v": 6}


def test_a_put_leaves_no_temporary_file_behind(tmp_path):
    cache = Cache(tmp_path)
    cache.put("k", {"v": 7})
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []


def test_an_interrupted_put_leaves_the_previous_value_intact(tmp_path, monkeypatch):
    """The point of write-then-rename: the reader never sees a partial write.

    The interrupt lands after the temporary file is written and before it is
    renamed into place, which is precisely the window the old non-atomic
    write_text left open.
    """
    import scholarmend.cache as cache_module

    cache = Cache(tmp_path)
    cache.put("k", {"v": 8})

    def explode(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(cache_module.os, "replace", explode)
    with pytest.raises(KeyboardInterrupt):
        cache.put("k", {"v": 9})

    assert cache.get("k") == {"v": 8}
    assert [p.name for p in tmp_path.rglob("*.tmp")] == []
