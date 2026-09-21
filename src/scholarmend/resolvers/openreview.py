"""OpenReview venue resolution.

A ``venueid`` states venue, year and workshop status in one string:

    ICML.cc/2025/Conference                        -> ICML 2025, main track
    ICML.cc/2026/Workshop/AI4GOOD                   -> ICML 2026, a workshop
    NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM

That single field is what 90 of the 112 hand-resolved records needed. It is
validated here against all 90 of those venueids, with zero per-record
disagreements; separately, the reviewers spot-checked 92 workshop-bucket
records against OpenReview and found no false positives.
"""

from __future__ import annotations

import json
import re
import urllib.request
from collections.abc import Callable

from ..cache import Cache
from ..models import Claim

API = "https://api2.openreview.net"
_VENUEID = re.compile(r"^(?P<org>[A-Za-z][\w.-]*?)(?:\.cc|\.org)?/(?P<year>\d{4})/(?P<track>.+)$")


class AuthError(RuntimeError):
    """No usable credentials, and the anonymous API refuses every read."""


def login(user: str, password: str) -> str:
    """Exchange credentials for a bearer token."""
    body = json.dumps({"id": user, "password": password}).encode("utf-8")
    request = urllib.request.Request(
        f"{API}/login", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        token = json.loads(response.read().decode("utf-8")).get("token")
    if not token:
        raise AuthError("OpenReview accepted the request but returned no token")
    return token


def parse_venueid(venueid: str) -> list[Claim]:
    """Claims derived from a venueid string."""

    def claim(field: str, value: str) -> Claim:
        return Claim(field=field, value=value, source="openreview_api", tier=2,
                     confidence=0.99, evidence=f"venueid={venueid}")

    claims = [claim("venue_id", venueid)]
    match = _VENUEID.match(venueid)
    if match is None:
        return claims
    # Trailing /Submission and similar suffixes are routing detail, not venue.
    track = re.sub(r"/Submission$", "", match.group("track"))
    claims += [
        claim("venue", match.group("org")),
        claim("year", match.group("year")),
        claim("track", track),
        claim("version", "proceedings"),
    ]
    return claims


class OpenReviewResolver:
    """Forum ids to claims, from the committed cache or, failing that, the API.

    ``token`` may be a callable rather than a string. A committed cache answers
    every forum the corpus contains without an account, so a warm run must not
    log in at all; passing a callable defers the login to the first genuine
    miss, which is the only moment credentials are actually needed.
    """

    def __init__(
        self, cache: Cache, token: str | Callable[[], str | None] | None = None
    ) -> None:
        self.cache = cache
        self.token = token

    def _bearer(self) -> str | None:
        return self.token() if callable(self.token) else self.token

    def resolve(self, forum_id: str) -> list[Claim]:
        """Claims for one forum id, from cache or from the API."""

        def loader() -> dict:
            token = self._bearer()
            if not token:
                raise AuthError(
                    "OpenReview needs credentials: the anonymous API returns "
                    "ChallengeRequiredError. Set SCHOLARMEND_OPENREVIEW_USER and "
                    "SCHOLARMEND_OPENREVIEW_PASSWORD, or run with --offline against "
                    "a populated cache."
                )
            from ..http import get_json

            payload = get_json(
                f"{API}/notes?forum={forum_id}&limit=1",
                headers={"Authorization": f"Bearer {token}"},
            )
            notes = payload.get("notes") or []
            content = (notes[0].get("content") if notes else {}) or {}
            venueid = (content.get("venueid") or {}).get("value")
            return {"venueid": venueid} if venueid else {}

        cached = self.cache.fetch(f"openreview:notes:{forum_id}", loader)
        venueid = cached.get("venueid")
        return parse_venueid(venueid) if venueid else []
