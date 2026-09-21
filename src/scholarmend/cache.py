"""A content-addressed response store, committed to the repository.

Reproducibility is the point. A systematic review is reported once and defended
for years; a rerun has to produce what the first run produced. Every cached file
records the key alongside the payload so that the store stays auditable by
reading it, rather than only by replaying it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path


class CacheMiss(RuntimeError):
    """Offline mode was asked for something the cache does not hold."""


class Cache:
    def __init__(self, root: Path, offline: bool = False) -> None:
        self.root = Path(root)
        self.offline = offline

    def _path(self, key: str) -> Path:
        # Hashing keeps arbitrary keys -- titles, URLs -- safe as filenames.
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.json"

    def get(self, key: str) -> dict | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))["payload"]
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as error:
            # A damaged entry is a miss, loudly. Raising instead would abort a
            # 2,413-record run over one unreadable file; staying silent would
            # hide a cache the repository is supposed to be able to audit.
            print(f"cache entry {path} is unreadable ({error}); treating as a miss",
                  file=sys.stderr)
            return None

    def put(self, key: str, payload: dict) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"key": key, "payload": payload}
        text = json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False)
        # Write-then-rename, because a run interrupted mid-write used to leave
        # truncated JSON behind, and the next run raised JSONDecodeError on a
        # file it had written itself. The temporary file shares the directory
        # so that the replace is atomic on one filesystem.
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=path.name, suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def fetch(self, key: str, loader: Callable[[], dict]) -> dict:
        """Cached value, or ``loader()`` stored and returned."""
        hit = self.get(key)
        if hit is not None:
            return hit
        if self.offline:
            raise CacheMiss(
                f"{key!r} is not cached and --offline forbids fetching it. "
                f"Run once without --offline to populate the cache."
            )
        payload = loader()
        self.put(key, payload)
        return payload
