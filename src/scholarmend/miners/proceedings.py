"""NeurIPS and ICLR proceedings URLs.

Both hosts use one grammar:

    https://proceedings.{neurips|iclr}.cc/paper_files/paper/{year}/
        {hash|file}/{sha}-{Abstract|Paper}-{Track}.{html|pdf}

Measured on the Trust-Evals-LitReview corpus, this covers 1,854 of 2,413
records -- 1,264 NeurIPS and 590 ICLR -- and yields venue, year and track for
every one of them without a network call.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..models import Claim

HOSTS = {
    "proceedings.neurips.cc": "NeurIPS",
    "papers.nips.cc": "NeurIPS",
    "proceedings.iclr.cc": "ICLR",
}

# Closed vocabulary, measured across the whole corpus. Every one is main track;
# workshop papers are never hosted at these paths, which is what makes this
# signal discriminate so cleanly.
TRACKS = frozenset(
    {
        "Conference",
        "Datasets_and_Benchmarks_Track",
        "Position_Paper_Track",
        "Creative_AI_Track",
    }
)

# Older spellings of a track in TRACKS, reported under the current name so one
# track never counts as two. NeurIPS 2023 and earlier omit the "_Track" suffix.
ALIASES = {"Datasets_and_Benchmarks": "Datasets_and_Benchmarks_Track"}

_PATH = re.compile(
    r"/paper_files/paper/(?P<year>\d{4})/(?:hash|file)/"
    r"[0-9a-f]+-(?:Abstract|Paper)-(?P<track>[A-Za-z_]+)\.(?:html|pdf)$"
)


class UnknownTrack(ValueError):
    """A proceedings URL named a track this miner does not know.

    Raised rather than defaulted, because defaulting to main track would
    silently misclassify a newly introduced track, and a false keep that looks
    confident is harder to notice than a crash.
    """


def mine(url: str) -> list[Claim]:
    """Claims derived from ``url``, or ``[]`` if it is not a proceedings URL."""
    parsed = urlparse(url)
    venue = HOSTS.get(parsed.netloc.lower())
    if venue is None:
        return []

    # The query string is dropped deliberately: one real URL in the corpus
    # carries ?utm_source=chatgpt.com, having been round-tripped through a
    # chatbot before reaching Scholar.
    match = _PATH.search(parsed.path)
    if match is None:
        return []

    track = ALIASES.get(match.group("track"), match.group("track"))
    if track not in TRACKS:
        raise UnknownTrack(f"{track!r} is not a known track, in {url!r}")

    def claim(field: str, value: str) -> Claim:
        return Claim(
            field=field,
            value=value,
            source="proceedings_url",
            tier=1,
            confidence=0.99,
            evidence=url,
        )

    return [
        claim("venue", venue),
        claim("year", match.group("year")),
        claim("track", track),
        claim("version", "proceedings"),
    ]
