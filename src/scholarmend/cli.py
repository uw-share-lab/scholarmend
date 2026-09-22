"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .cache import Cache, CacheMiss
from .emit import project_ris, to_json
from .http import HttpError
from .parse import parse_file
from .pipeline import RESOLVED_FIELDS, resolve_record
from .resolvers.openreview import AuthError, OpenReviewResolver, login
from .resolvers.pmc import PmcResolver
from .resolvers.pmlr_index import PmlrIndexResolver
from .resolvers.proceedings_page import ProceedingsPageResolver
from .resolvers.semanticscholar import SemanticScholarResolver


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scholarmend",
        description="Recover true venue, year and track for Google Scholar RIS exports.",
    )
    parser.add_argument("--input", required=True, type=Path,
                        help="a .ris file, or a directory of them")
    parser.add_argument("--out", required=True, type=Path, help="directory to write outputs to")
    parser.add_argument("--cache", default=Path(".scholarmend-cache"), type=Path,
                        help="response cache; commit it for reproducibility")
    parser.add_argument("--offline", action="store_true",
                        help="never call the network; fail on a cache miss")
    parser.add_argument("--abstracts", action="store_true",
                        help="replace Scholar's AB snippet with the full abstract, from the "
                             "proceedings page, OpenReview or Semantic Scholar")
    return parser


def _report(documents: list[dict], unresolved: list[tuple[str, list[str]]],
            abstracts_requested: bool = False) -> str:
    """What a human still has to look at, with the structurally impossible removed.

    A field no source in this run could supply -- doi, which nothing resolved
    for any of the 2,413 records -- accused every record of a failure no human
    could act on, and buried the genuinely unresolved venues and years under
    1,854 lines of noise. Emptiness across the whole corpus is the evidence
    that no source exists for it, so the field is named once and then left out
    of the per-record list.
    """
    supplied = {field for field in RESOLVED_FIELDS
                if any(doc["fields"][field].get("value") for doc in documents)}
    absent = [f for f in RESOLVED_FIELDS if f not in supplied]

    rows = [(title, [f for f in missing if f in supplied]) for title, missing in unresolved]
    rows = [(title, missing) for title, missing in rows if missing]
    # Venue and year are the deliverable; a record missing one of them comes
    # first, so that truncating the list cannot hide it.
    rows.sort(key=lambda row: not ({"venue", "year"} & set(row[1])))

    counts = " ".join(
        f"{field}={sum(1 for _, missing in rows if field in missing)}" for field in RESOLVED_FIELDS
    )
    lines = [
        f"records: {len(documents)}",
        f"records with unresolved fields: {len(rows)}",
        f"unresolved by field: {counts}",
    ]
    if absent:
        lines.append(
            f"no source in this run could supply: {','.join(absent)} (excluded above and below)"
        )
    # Scholar's AB always "resolves", to its own snippet, so the count above
    # cannot show these. They are the records a screener reads a fragment for.
    snippets = [doc["title"] for doc in documents
                if abstracts_requested and doc["fields"]["abstract"].get("source") == "scholar"]
    if abstracts_requested:
        lines.append(f"abstract still Scholar's snippet: {len(snippets)}")
    lines.append("")
    for title, missing in rows[:200]:
        lines.append(f"  unresolved {','.join(missing):28s} {title[:70]}")
    if snippets:
        lines.append("")
    for title in snippets:
        lines.append(f"  snippet    {title[:70]}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    # A single file is how venuetriage's clean.ris -- the Covidence upload,
    # already deduplicated and triaged -- gets its abstracts: its directory
    # also holds removed.ris, which must not be merged into the upload.
    files = [args.input] if args.input.is_file() else sorted(args.input.glob("*.ris"))
    if not files:
        print(f"no .ris files in {args.input}", file=sys.stderr)
        return 2

    cache = Cache(args.cache, offline=args.offline)
    degraded = False

    user = os.environ.get("SCHOLARMEND_OPENREVIEW_USER")
    password = os.environ.get("SCHOLARMEND_OPENREVIEW_PASSWORD")
    credentialed = bool(user and password) and not args.offline
    warm = args.cache.exists()
    token: dict[str, str | None] = {}

    def openreview_token() -> str | None:
        """Log in on the first genuine cache miss, and never before.

        A committed cache holds every answer tier 2 needs, so a warm run must
        make no API call at all -- including the login the run used to perform
        unconditionally. Deferring it here is what makes the README's "makes no
        API calls" true of the path a third party actually runs.
        """
        nonlocal degraded
        if not credentialed:
            return None
        if "value" not in token:
            try:
                token["value"] = login(str(user), str(password))
            except Exception as error:  # noqa: BLE001 - degrade, never crash the run
                print(f"OpenReview login failed, continuing on tier 1: {error}", file=sys.stderr)
                degraded = True
                token["value"] = None
        return token["value"]

    if not credentialed and not args.offline:
        if warm:
            # The reproducibility path: a committed cache and no account. Tier 2
            # is not disabled here -- only a forum the cache does not hold will
            # degrade this run, one record at a time.
            print("no OpenReview credentials; tier 2 served from the cache", file=sys.stderr)
        else:
            print("no OpenReview credentials and no cache; tier 2 disabled", file=sys.stderr)
            degraded = True

    # Gate on whether an answer is reachable at all, not on credentials alone.
    openreview = (
        OpenReviewResolver(cache, openreview_token)
        if (credentialed or warm or args.offline)
        else None
    )
    pmlr_index = PmlrIndexResolver(cache)
    pmc = PmcResolver(cache)
    semanticscholar = SemanticScholarResolver(cache, os.environ.get("SCHOLARMEND_S2_KEY"))
    proceedings_page = ProceedingsPageResolver(cache)

    abstract_errors: list[str] = []

    def abstract_failed(error: Exception) -> None:
        """An abstract lookup failed: keep the snippet, and say so once."""
        nonlocal degraded
        if not abstract_errors:
            print(f"some abstracts not recovered, Scholar's snippet kept: {error}",
                  file=sys.stderr)
        abstract_errors.append(str(error))
        degraded = True

    documents, projections, unresolved = [], [], []
    for path in files:
        for record in parse_file(path):
            try:
                ledger = resolve_record(record, openreview=openreview,
                                        pmlr_index=pmlr_index, pmc=pmc,
                                        semanticscholar=semanticscholar,
                                        proceedings_page=proceedings_page,
                                        abstracts=args.abstracts,
                                        on_error=abstract_failed)
            except (AuthError, CacheMiss, HttpError) as error:
                # Degrade, never abort. One unreachable lookup must not cost
                # the other 2,412 records their tier-1 resolution, which needs
                # no network at all. The run reports itself partial via exit 1.
                if not degraded:
                    print(f"falling back to tier 1 for some records: {error}", file=sys.stderr)
                degraded = True
                # The proceedings page needs no key the failed lookup could
                # have supplied, so the abstract is still worth trying.
                ledger = resolve_record(record, openreview=None, pmlr_index=None,
                                        pmc=None, semanticscholar=None,
                                        proceedings_page=proceedings_page,
                                        abstracts=args.abstracts,
                                        on_error=abstract_failed)
            documents.append(to_json(record, ledger))
            projections.append(project_ris(record, ledger))
            unresolved.append((record.title, [f for f in RESOLVED_FIELDS
                                              if ledger.is_unresolved(f)]))

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "resolved.json").write_text(
        json.dumps(documents, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    # utf-8-sig, because parse_file reads utf-8-sig: without the BOM the file
    # round-trips record by record but not as a file.
    (args.out / "mended.ris").write_text("".join(projections), encoding="utf-8-sig")

    (args.out / "report.txt").write_text(_report(documents, unresolved, args.abstracts), encoding="utf-8")

    recovered = sum(1 for doc in documents
                    if doc["fields"]["abstract"].get("source") not in (None, "scholar"))
    print(f"wrote {len(documents)} records to {args.out}")
    if args.abstracts:
        print(f"{recovered} with a recovered abstract; "
              f"{len(abstract_errors)} abstract lookups failed")
    return 1 if degraded else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
