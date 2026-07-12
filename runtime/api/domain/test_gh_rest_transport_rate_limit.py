"""Tests for rate-limit recognition in the bearer-token GitHub REST transport.

Covers the typed `RateLimitedError` class introduced for both canonical 429
responses and the 403-shaped secondary rate limit GitHub returns when the
authenticated identity exceeds its hourly REST budget or trips the abuse
heuristic.

Sibling of `test_gh_rest_transport.py`; split out to keep each test file
under the 350-line cap.
"""

from __future__ import annotations

import io
import urllib.error

import pytest

from yoke_core.domain import gh_rest_transport as t


class _FakeResponse:
    """Mimic the urlopen() context-manager return value."""

    def __init__(
        self, *, status: int, body: bytes, headers: dict[str, str] | None = None
    ):
        self.status = status
        self._body = body
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1):
        return self._body if size < 0 else self._body[:size]


def _make_http_error(status: int, body: bytes) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=status,
        msg=f"HTTP {status}",
        hdrs={"Content-Type": "application/json"},  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )


@pytest.fixture(autouse=True)
def _silent_backoff(monkeypatch):
    """Make backoff sleeps a no-op so retry tests stay fast."""
    monkeypatch.setattr(t, "sleep", lambda _seconds: None)


def test_429_classifies_as_rate_limited(monkeypatch):
    """Canonical 429 returns RateLimitedError after retry budget exhausts."""

    def fake_urlopen(request, timeout):
        raise _make_http_error(429, b'{"message":"rate limit exceeded"}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RateLimitedError) as excinfo:
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghs_x")
    assert excinfo.value.status == 429


def test_403_with_rate_limit_body_classifies_as_rate_limited(monkeypatch):
    """Secondary 403-shaped rate limit retries like 429, terminal as RateLimitedError."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        raise _make_http_error(
            403,
            b'{"message":"API rate limit exceeded for user ID 12345"}',
        )

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RateLimitedError) as excinfo:
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghs_x")
    assert excinfo.value.status == 403
    # Three attempts proves the retry budget was applied — without
    # RateLimitedError recognition, a 403 would have terminated on the
    # first try as RestAuthError.
    assert calls["n"] == 3


def test_403_with_secondary_rate_limit_marker_retries_then_succeeds(monkeypatch):
    """'secondary rate limit' body marker also classifies as rate-limited."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(
                403,
                b'{"message":"You have exceeded a secondary rate limit"}',
            )
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghs_x")
    assert calls["n"] == 2


def test_403_with_abuse_marker_retries_then_succeeds(monkeypatch):
    """'abuse detection mechanism' body marker classifies as rate-limited."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(
                403,
                b'{"message":"You have triggered an abuse detection mechanism"}',
            )
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghs_x")
    assert calls["n"] == 2


@pytest.mark.parametrize(
    "body,expected",
    [
        ("API rate limit exceeded", True),
        ("secondary rate limit", True),
        ("abuse detection mechanism", True),
        ("Resource not accessible by integration", False),
        ("Bad credentials", False),
        ("", False),
    ],
)
def test_is_rate_limit_body_recognition(body, expected):
    assert t._is_rate_limit_body(body) is expected


def test_rate_limited_error_is_retryable():
    """RateLimitedError is classified retryable regardless of HTTP status."""
    exc = t.RateLimitedError("HTTP 403 rate limit: ...", status=403, body="")
    assert t._is_retryable_error(exc) is True


def test_rest_auth_error_is_not_retryable():
    """Non-rate-limit 403 (RestAuthError) is NOT retried by the transport."""
    exc = t.RestAuthError("HTTP 403: Bad credentials", status=403, body="")
    assert t._is_retryable_error(exc) is False
