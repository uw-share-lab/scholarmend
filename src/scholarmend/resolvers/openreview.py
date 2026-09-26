"""OpenReview venue resolution.

A ``venueid`` states venue, year and workshop status in one string:

    ICML.cc/2025/Conference                        -> ICML 2025, main track
    ICML.cc/2026/Workshop/AI4GOOD                   -> ICML 2026, a workshop
    NeurIPS.cc/2025/Workshop_Mexico_City/ResponsibleFM
    ICLR.cc/2025/Conference/Rejected_Submission     -> submitted, not published

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
API_V1 = "https://api.openreview.net"
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


# What a withdrawn or non-public submission answers, to any account. Matched
# on the message, because a bare 403 could as well be an expired session.
_HIDDEN = "does not have permission to see"

# Cached for such a forum instead of the 403 itself: the refusal names the
# logged-in user, and this cache is committed to a public repository. Delete
# the entry to ask again, if the forum may since have been made public.
HIDDEN = {"hidden": True}


def _flatten(content: dict) -> dict:
    """API v2 wraps each field as {"value": ...}; v1 stores it bare."""
    return {name: field.get("value") if isinstance(field, dict) else field
            for name, field in (content or {}).items()}


def submission_note(forum_id: str, token: str) -> dict | None:
    """The forum's submission note with plain-valued content, or ``None``.

    Asked of API v2 first. Some 2022-2023 workshops were never migrated and
    exist only on v1, where api2 answers 404 (verified live 2026-09-25 on
    LpBlkATV24M, NeurIPS.cc/2022/Workshop/RobustSeq). A forum the account may
    not see comes back as ``HIDDEN``. Anything else propagates as a failure,
    which the cache never stores.
    """
    from ..http import HttpError, get_json

    headers = {"Authorization": f"Bearer {token}"}
    try:
        payload = get_json(f"{API}/notes?id={forum_id}", headers=headers)
        api = "v2"
    except HttpError as error:
        if error.status == 403 and _HIDDEN in error.body:
            return HIDDEN
        if error.status != 404:
            raise
        try:
            payload = get_json(f"{API_V1}/notes?id={forum_id}", headers=headers)
        except HttpError as v1_error:
            if v1_error.status == 404:
                raise error from v1_error
            raise
        api = "v1"
    notes = payload.get("notes") or []
    note = notes[0] if notes else {}
    if note.get("id") != forum_id:
        return None
    return {"api": api, "content": _flatten(note.get("content") or {})}


def openreview_key(forum_id: str) -> str:
    """The cache key for one forum's venueid. Tests build keys with this too.

    ``openreview:note:`` replaced ``openreview:notes:`` when the lookup changed
    from ``?forum=…&limit=1`` to ``?id=…``. Entries under the old prefix may
    hold a venueid derived from a Decision note's invitation, which cannot
    show acceptance, and nothing distinguishes them from direct ones -- so the
    old prefix is simply no longer read.
    """
    return f"openreview:note:{forum_id}"


def parse_venueid(venueid: str) -> list[Claim]:
    """Claims derived from a venueid string."""

    def claim(field: str, value: str) -> Claim:
        return Claim(field=field, value=value, source="openreview_api", tier=2,
                     confidence=0.99, evidence=f"venueid={venueid}")

    claims = [claim("venue_id", venueid)]
    match = _VENUEID.match(venueid)
    if match is None:
        return claims
    # OpenReview gives an accepted paper the bare venue (".../Conference") and
    # keeps a *Submission suffix on everything else: under review, rejected,
    # withdrawn, desk-rejected. The suffix is the acceptance status, not
    # routing detail, so the track is kept verbatim and such a paper is not
    # claimed as proceedings. Venue and year stay: they say where and when it
    # was submitted, which is true either way.
    track = match.group("track")
    claims += [
        claim("venue", match.group("org")),
        claim("year", match.group("year")),
        claim("track", track),
    ]
    if not track.endswith("Submission"):
        claims.append(claim("version", "proceedings"))
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
            # The forum id is the submission note's own id, and the
            # submission note is the one that states content.venueid. Asking
            # for "any note in the forum" returned a Decision note on 25 of 96
            # real forums, and deriving a venue from its invitation turned a
            # rejected ICLR paper into ICLR main track (verified live,
            # zkNCWtw2fd). A note that does not state its own venueid records
            # nothing: unresolved goes to a human, derived does not.
            note = submission_note(forum_id, token)
            if note is HIDDEN:
                return HIDDEN
            if note is None:
                return {}
            venueid = note["content"].get("venueid")
            if not venueid:
                return {}
            # v2 entries keep their original shape; only a v1 answer says so.
            return {"venueid": venueid, "api": "v1"} if note["api"] == "v1" else {"venueid": venueid}

        cached = self.cache.fetch(openreview_key(forum_id), loader)
        venueid = cached.get("venueid")
        return parse_venueid(venueid) if venueid else []

    def abstract(self, forum_id: str, title: str) -> list[Claim]:
        """The submission note's own abstract, under a key of its own.

        Kept apart from ``openreview_key`` so that the venueid entries -- each
        validated against the reviewers' labels -- are neither refetched nor
        rewritten to add a field they never needed.
        """
        from .proceedings_page import one_line
        from .semanticscholar import titles_match

        def loader() -> dict:
            token = self._bearer()
            if not token:
                raise AuthError("OpenReview needs credentials to fetch an abstract")
            note = submission_note(forum_id, token)
            if note is HIDDEN:
                return HIDDEN
            if note is None:
                return {}
            content = note["content"]
            return {
                "title": content.get("title") or "",
                "abstract": content.get("abstract") or "",
            }

        cached = self.cache.fetch(abstract_key(forum_id), loader)
        text = one_line(cached.get("abstract") or "")
        if not text or not titles_match(title, cached.get("title") or ""):
            return []
        return [Claim(field="abstract", value=text, source="openreview_api", tier=2,
                      confidence=0.99, evidence=f"openreview:{forum_id}")]


def abstract_key(forum_id: str) -> str:
    return f"openreview:abstract:{forum_id}"
