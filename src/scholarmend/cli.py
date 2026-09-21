"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .cache import Cache
from .emit import project_ris, to_json
from .parse import parse_file
from .pipeline import RESOLVED_FIELDS, resolve_record
from .cache import CacheMiss
from .http import HttpError
from .resolvers.openreview import AuthError, OpenReviewResolver, login
from .resolvers.pmc import PmcResolver
from .resolvers.pmlr_index import PmlrIndexResolver
from .resolvers.semanticscholar import SemanticScholarResolver


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarmend",
        description="Recover true venue, year and track for Google Scholar RIS exports.",
    )
    parser.add_argument("--input", required=True, type=Path, help="directory of .ris files")
    parser.add_argument("--out", required=True, type=Path, help="directory to write outputs to")
    parser.add_argument("--cache", default=Path(".scholarmend-cache"), type=Path,
                        help="response cache; commit it for reproducibility")
    parser.add_argument("--offline", action="store_true",
                        help="never call the network; fail on a cache miss")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    files = sorted(args.input.glob("*.ris"))
    if not files:
        print(f"no .ris files in {args.input}", file=sys.stderr)
        return 2

    cache = Cache(args.cache, offline=args.offline)
    degraded = False

    token = None
    user = os.environ.get("SCHOLARMEND_OPENREVIEW_USER")
    password = os.environ.get("SCHOLARMEND_OPENREVIEW_PASSWORD")
    if user and password and not args.offline:
        try:
            token = login(user, password)
        except Exception as error:  # noqa: BLE001 - degrade, never crash the run
            print(f"OpenReview login failed, continuing on tier 1: {error}", file=sys.stderr)
            degraded = True
    elif not args.offline:
        print("no OpenReview credentials; tier 2 disabled", file=sys.stderr)
        degraded = True

    openreview = OpenReviewResolver(cache, token) if (token or args.offline) else None
    pmlr_index = PmlrIndexResolver(cache)
    pmc = PmcResolver(cache)
    semanticscholar = SemanticScholarResolver(cache, os.environ.get("SCHOLARMEND_S2_KEY"))

    documents, projections, unresolved = [], [], []
    for path in files:
        for record in parse_file(path):
            try:
                ledger = resolve_record(record, openreview=openreview,
                                        pmlr_index=pmlr_index, pmc=pmc,
                                        semanticscholar=semanticscholar)
            except (AuthError, CacheMiss, HttpError) as error:
                # Degrade, never abort. One unreachable lookup must not cost
                # the other 2,412 records their tier-1 resolution, which needs
                # no network at all. The run reports itself partial via exit 1.
                if not degraded:
                    print(f"falling back to tier 1 for some records: {error}", file=sys.stderr)
                degraded = True
                ledger = resolve_record(record, openreview=None, pmlr_index=None,
                                        pmc=None, semanticscholar=None)
            documents.append(to_json(record, ledger))
            projections.append(project_ris(record, ledger))
            missing = [f for f in RESOLVED_FIELDS if ledger.is_unresolved(f)]
            if missing:
                unresolved.append((record.title, missing))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "resolved.json").write_text(
        json.dumps(documents, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    (args.out / "mended.ris").write_text("".join(projections), encoding="utf-8")

    lines = [f"records: {len(documents)}", f"records with unresolved fields: {len(unresolved)}", ""]
    for title, missing in unresolved[:200]:
        lines.append(f"  unresolved {','.join(missing):28s} {title[:70]}")
    (args.out / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {len(documents)} records to {args.out}")
    return 1 if degraded else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
