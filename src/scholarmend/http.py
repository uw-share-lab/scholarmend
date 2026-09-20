"""A small JSON-over-HTTP client.

stdlib only, matching refaudit's decision to carry no runtime dependencies:
this gets installed in a hurry, close to a deadline, often on a machine someone
else administers.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


class HttpError(RuntimeError):
    pass


# The largest window any server here advertises is one hour. Cap the wait so a
# malformed or hostile header cannot park a run indefinitely.
MAX_RATELIMIT_WAIT = 3700.0


def _respect_rate_limit(response, sleep=time.sleep) -> None:
    """Pause when the server says the budget is spent.

    OpenReview advertises ``ratelimit-policy: 500;w=3600`` -- 500 requests an
    hour, per token. Tier 2 needs 527 forum lookups, so an unbroken run runs
    out 27 calls from the end. Waiting for the window to roll over turns that
    from a failed run into a slow one, and because every response is cached,
    the wait is paid once ever rather than once per run.
    """
    remaining = response.headers.get("ratelimit-remaining")
    if remaining is None or not remaining.strip().isdigit():
        return
    if int(remaining) > 0:
        return
    reset = response.headers.get("ratelimit-reset", "")
    seconds = float(reset) if reset.strip().replace(".", "", 1).isdigit() else 60.0
    sleep(min(max(seconds, 0.0), MAX_RATELIMIT_WAIT) + 1.0)


def get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 20.0,
    attempts: int = 3,
) -> dict:
    """GET ``url`` and parse JSON, retrying on transient failure.

    429 and 5xx are retried with exponential backoff; 4xx other than 429 is
    raised at once, because retrying a refusal only spends someone else's
    rate limit.
    """
    last: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                _respect_rate_limit(response)
                return payload
        except urllib.error.HTTPError as error:
            last = error
            if error.code != 429 and error.code < 500:
                raise HttpError(f"{error.code} from {url}") from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            last = error
        if attempt < attempts - 1:
            time.sleep(2.0**attempt)
    raise HttpError(f"giving up on {url}: {last!r}")
