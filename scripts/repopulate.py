#!/usr/bin/env python3
"""Repopulate cache entries poisoned by a resolver bug that has since been fixed.

``Cache.fetch`` returns a cached value without retrying, so an empty result
captured before a resolver fix is wrong forever unless someone deletes it and
looks the record up again. This script does that, narrowly: it only touches
entries whose payload is the specific "nothing recovered" shape a resolver
loader returns on failure (``{}``, or a PMLR payload with ``title == ""``),
re-fetches exactly those keys through the current (fixed) resolvers, and
leaves every other entry in the committed cache untouched.

Usage::

    set -a; . ./.env; set +a
    .venv/bin/python scripts/repopulate.py [--cache .scholarmend-cache]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scholarmend.cache import Cache, CacheMiss
from scholarmend.http import HttpError
from scholarmend.resolvers.openreview import AuthError, OpenReviewResolver, login
from scholarmend.resolvers.pmlr_index import PmlrIndexResolver

OPENREVIEW_PREFIX = "openreview:notes:"
PMLR_PREFIX = "pmlr:volume:"


def _is_empty(key: str, payload: dict) -> bool:
    if key.startswith(OPENREVIEW_PREFIX):
        return payload == {}
    if key.startswith(PMLR_PREFIX):
        return payload.get("title", "") == ""
    return False


def _poisoned_entries(cache_root: Path) -> list[tuple[Path, str]]:
    """(file path, key) for every cache entry this script is allowed to touch."""
    found = []
    for path in sorted(cache_root.glob("*/*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        key = document.get("key", "")
        payload = document.get("payload", {})
        if isinstance(payload, dict) and _is_empty(key, payload):
            found.append((path, key))
    return found


# A lookup that could not be made. URLError and TimeoutError are OSErrors;
# PMLR calls urllib directly, so its failures arrive as those, not HttpError.
FAILURES = (AuthError, CacheMiss, HttpError, OSError)


@dataclass
class Result:
    recovered: int = 0
    still_empty: int = 0
    failed: int = 0


def repopulate(
    cache: Cache,
    resolve_openreview: Callable[[str], object] | None,
    resolve_pmlr: Callable[[str], object],
    delay: float,
) -> Result:
    """Refetch each poisoned entry, never losing one.

    Each entry is set aside, not deleted, and put back unless a replacement
    was actually written -- on a failed lookup, and on Ctrl-C. The old script
    deleted every entry first and then refetched unguarded, so one AuthError
    cost the committed cache ~29 entries (BACKLOG §3).
    """
    result = Result()
    for path, key in _poisoned_entries(cache.root):
        if key.startswith(OPENREVIEW_PREFIX):
            if resolve_openreview is None:
                continue
            ident, resolve = key[len(OPENREVIEW_PREFIX):], resolve_openreview
        else:
            ident, resolve = key[len(PMLR_PREFIX):], resolve_pmlr

        aside = path.with_name(path.name + ".aside")
        path.replace(aside)
        failed = False
        try:
            resolve(ident)
        except FAILURES as error:
            failed = True
            print(f"  kept {key}: refetch failed ({error})", file=sys.stderr)
        finally:
            if path.exists():
                aside.unlink()
            else:
                aside.replace(path)  # nothing replaced it: put the original back
        if key.startswith(OPENREVIEW_PREFIX) and delay:
            time.sleep(delay)

        # Exactly one bucket per entry.
        if failed:
            result.failed += 1
        elif _is_empty(key, cache.get(key) or {}):
            result.still_empty += 1
            print(f"  still empty after refetch: {key}", file=sys.stderr)
        else:
            result.recovered += 1
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=Path(".scholarmend-cache"), type=Path)
    parser.add_argument("--delay", default=0.4, type=float,
                        help="seconds between OpenReview calls (default 0.4)")
    args = parser.parse_args(argv)

    poisoned = _poisoned_entries(args.cache)
    openreview_count = sum(1 for _, k in poisoned if k.startswith(OPENREVIEW_PREFIX))
    print(f"before: {len(poisoned)} poisoned entries ({openreview_count} openreview, "
          f"{len(poisoned) - openreview_count} pmlr)")

    cache = Cache(args.cache)
    user = os.environ.get("SCHOLARMEND_OPENREVIEW_USER")
    password = os.environ.get("SCHOLARMEND_OPENREVIEW_PASSWORD")
    resolve_openreview = None
    if user and password:
        token: dict[str, str] = {}

        def openreview_token() -> str:
            if "value" not in token:
                token["value"] = login(user, password)
            return token["value"]

        resolve_openreview = OpenReviewResolver(cache, openreview_token).resolve
    elif openreview_count:
        print(f"no OpenReview credentials: leaving all {openreview_count} openreview "
              f"entries untouched", file=sys.stderr)

    result = repopulate(cache, resolve_openreview, PmlrIndexResolver(cache).resolve, args.delay)
    print(f"after: {result.recovered} recovered, {result.still_empty} still empty, "
          f"{result.failed} failed and kept")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
