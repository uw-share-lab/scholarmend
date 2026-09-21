"""Suite-wide guards."""

from __future__ import annotations

import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Fail loudly if any test tries to open a real connection.

    A test that reaches the network is not merely slow: it passes or fails on
    someone else's rate limit rather than on this code. The failure that
    prompted this guard looked like a normal assertion error, three layers
    down, on a title that happened to normalise differently from its
    hardcoded cache key.
    """

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test attempted a real network call; use a pre-populated Cache "
            "and build keys with the same helper production uses"
        )

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
