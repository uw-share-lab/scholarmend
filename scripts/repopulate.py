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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from scholarmend.cache import Cache
from scholarmend.resolvers.openreview import OpenReviewResolver, login
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", default=Path(".scholarmend-cache"), type=Path)
    parser.add_argument("--delay", default=0.4, type=float,
                        help="seconds between OpenReview calls (default 0.4)")
    args = parser.parse_args(argv)

    poisoned = _poisoned_entries(args.cache)
    before = len(poisoned)
    print(f"before: {before} poisoned entries "
          f"({sum(1 for _, k in poisoned if k.startswith(OPENREVIEW_PREFIX))} openreview, "
          f"{sum(1 for _, k in poisoned if k.startswith(PMLR_PREFIX))} pmlr)")

    for path, _key in poisoned:
        path.unlink()

    cache = Cache(args.cache)

    user = os.environ.get("SCHOLARMEND_OPENREVIEW_USER")
    password = os.environ.get("SCHOLARMEND_OPENREVIEW_PASSWORD")
    token: dict[str, str | None] = {}

    def openreview_token() -> str | None:
        if not (user and password):
            return None
        if "value" not in token:
            token["value"] = login(user, password)
        return token["value"]

    openreview = OpenReviewResolver(cache, openreview_token)
    pmlr_index = PmlrIndexResolver(cache)

    fixed = 0
    still_empty = 0
    for _path, key in poisoned:
        if key.startswith(OPENREVIEW_PREFIX):
            forum_id = key[len(OPENREVIEW_PREFIX):]
            openreview.resolve(forum_id)
            time.sleep(args.delay)
        elif key.startswith(PMLR_PREFIX):
            volume = key[len(PMLR_PREFIX):]
            pmlr_index.resolve(volume)
        payload = cache.get(key) or {}
        if _is_empty(key, payload):
            still_empty += 1
            print(f"  still empty after refetch: {key}", file=sys.stderr)
        else:
            fixed += 1

    after = still_empty
    print(f"after: {after} still-empty of {before} refetched ({fixed} recovered)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
