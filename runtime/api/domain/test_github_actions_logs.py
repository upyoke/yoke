"""Tests for per-job GitHub Actions log reads.

Covers:

- The per-job text endpoint reads one exact job, redacted.
- 401 / 403 raise typed :class:`RestAuthError`; 404 :class:`RestNotFoundError`.
- 5xx surfaces after the shared retry budget; a transient 5xx recovers.
- Log redirects stay on HTTPS and drop GitHub auth across origins.
- The complete-log download address is read from the redirect, unfollowed.

Which jobs of a run are read, and how they are reported, is covered by
``test_github_actions_failed_jobs.py``.
"""

from __future__ import annotations

import io
import urllib.error
import urllib.request
from typing import Any, Dict, List

import pytest

from yoke_core.domain import github_actions_logs
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
)


class _FakeResponse:
    """``urlopen`` context-manager substitute that yields bytes."""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.headers: Dict[str, str] = {}

    def read(self, size: int = -1) -> bytes:
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def close(self) -> None:
        return None


def _make_http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/x", status, "synthetic", {}, io.BytesIO(body)
    )


def _install_urlopen(monkeypatch, responses: List[Any]) -> List[str]:
    """Install a fake urlopen on the logs module; return URL call log."""
    calls: List[str] = []
    iterator = iter(responses)

    def _fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        calls.append(url)
        try:
            payload = next(iterator)
        except StopIteration:  # pragma: no cover - fixture misuse
            raise AssertionError("urlopen called more times than responses")
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, bytes):
            return _FakeResponse(payload)
        return payload

    monkeypatch.setattr(github_actions_logs, "urlopen", _fake_urlopen)
    monkeypatch.setattr(github_actions_logs, "sleep", lambda _s: None)
    return calls


class TestLogRedirects:
    def test_cross_origin_redirect_strips_authorization(self):
        handler = github_actions_logs._AuthorizationSafeRedirectHandler()
        request = urllib.request.Request(
            "https://api.github.com/repos/o/r/actions/jobs/1/logs",
            headers={"Authorization": "Bearer secret", "X-Test": "kept"},
        )

        redirected = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://productionresultssa0.blob.core.windows.net/job-1.txt",
        )

        assert redirected is not None
        headers = {key.lower(): value for key, value in redirected.header_items()}
        assert "authorization" not in headers
        assert headers["x-test"] == "kept"

    def test_redirect_rejects_plain_http(self):
        handler = github_actions_logs._AuthorizationSafeRedirectHandler()
        request = urllib.request.Request("https://api.github.com/logs")

        with pytest.raises(urllib.error.URLError, match="HTTPS"):
            handler.redirect_request(
                request, None, 302, "Found", {}, "http://archive.example/log"
            )


class TestFetchJobLog:
    def test_fetch_job_log_reads_exact_failed_attempt(self, monkeypatch):
        calls = _install_urlopen(monkeypatch, [b"authentication required\n"])

        result = github_actions_logs.fetch_job_log(
            "o/r",
            "99067752381",
            token="ghs_x",
        )

        assert result == "authentication required\n"
        assert "/actions/jobs/99067752381/logs" in calls[0]

    def test_token_in_log_text_is_redacted(self, monkeypatch):
        _install_urlopen(monkeypatch, [b"leaked ghs_secret here\n"])

        result = github_actions_logs.fetch_job_log("o/r", "1", token="ghs_secret")

        assert "ghs_secret" not in result

    def test_empty_token_raises_auth_error(self):
        with pytest.raises(RestAuthError):
            github_actions_logs.fetch_job_log("o/r", "1", token="")

    @pytest.mark.parametrize("status", [401, 403])
    def test_auth_refusal_raises_typed_auth_error(self, monkeypatch, status):
        _install_urlopen(monkeypatch, [_make_http_error(status, b"forbidden")])

        with pytest.raises(RestAuthError) as exc_info:
            github_actions_logs.fetch_job_log("o/r", "1", token="ghs_x")

        assert exc_info.value.status == status

    def test_404_raises_typed_not_found(self, monkeypatch):
        _install_urlopen(monkeypatch, [_make_http_error(404)])

        with pytest.raises(RestNotFoundError) as exc_info:
            github_actions_logs.fetch_job_log("o/r", "1", token="ghs_x")

        assert exc_info.value.status == 404

    def test_5xx_retries_then_surfaces(self, monkeypatch):
        responses = [
            _make_http_error(500, b"upstream error"),
            _make_http_error(502, b"bad gateway"),
            _make_http_error(503, b"unavailable"),
        ]
        _install_urlopen(monkeypatch, responses)

        with pytest.raises(RestServerError) as exc_info:
            github_actions_logs.fetch_job_log("o/r", "1", token="ghs_x")

        assert exc_info.value.status in (500, 502, 503)

    def test_5xx_then_success_returns_text(self, monkeypatch):
        _install_urlopen(monkeypatch, [_make_http_error(503), b"FAILED test_x\n"])

        assert github_actions_logs.fetch_job_log("o/r", "1", token="ghs_x") == (
            "FAILED test_x\n"
        )

    def test_no_token_in_error_text(self, monkeypatch):
        """Typed errors must not echo the bearer token."""
        _install_urlopen(monkeypatch, [_make_http_error(401, b"Bad credentials")])
        secret = "ghs_secret_token_must_not_leak"

        with pytest.raises(RestAuthError) as exc_info:
            github_actions_logs.fetch_job_log("o/r", "1", token=secret)

        rendered = f"{exc_info.value} | body={exc_info.value.body}"
        assert secret not in rendered


def _redirect(location: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/repos/o/r/actions/jobs/7/logs",
        302,
        "Found",
        {"Location": location},
        io.BytesIO(b""),
    )


def _install_no_redirect(monkeypatch, outcome: Any) -> List[str]:
    calls: List[str] = []

    def _fake(request, timeout=None):
        calls.append(request.full_url)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(github_actions_logs, "no_redirect_urlopen", _fake)
    return calls


class TestJobLogDownloadUrl:
    def test_returns_the_signed_redirect_target_without_following_it(self, monkeypatch):
        signed = "https://results.blob.core.windows.net/logs/7.txt?sig=abc"
        calls = _install_no_redirect(monkeypatch, _redirect(signed))

        url = github_actions_logs.job_log_download_url("o/r", "7", token="ghs_x")

        assert url == signed
        assert calls == ["https://api.github.com/repos/o/r/actions/jobs/7/logs"]

    def test_plain_http_target_is_refused(self, monkeypatch):
        _install_no_redirect(monkeypatch, _redirect("http://example.test/7.txt"))

        with pytest.raises(RestTransportError, match="non-HTTPS"):
            github_actions_logs.job_log_download_url("o/r", "7", token="ghs_x")

    def test_expired_log_raises_not_found(self, monkeypatch):
        _install_no_redirect(monkeypatch, _make_http_error(410, b"gone"))

        with pytest.raises(RestNotFoundError):
            github_actions_logs.job_log_download_url("o/r", "7", token="ghs_x")

    def test_refusal_raises_auth_error(self, monkeypatch):
        _install_no_redirect(monkeypatch, _make_http_error(403, b"forbidden"))

        with pytest.raises(RestAuthError):
            github_actions_logs.job_log_download_url("o/r", "7", token="ghs_x")

    def test_answer_without_redirect_is_refused_by_name(self, monkeypatch):
        _install_no_redirect(monkeypatch, _FakeResponse(b"body"))

        with pytest.raises(RestTransportError, match="without a download redirect"):
            github_actions_logs.job_log_download_url("o/r", "7", token="ghs_x")
