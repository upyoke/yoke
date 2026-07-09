"""Tests for the failed-log ZIP fetch + parse path.

Covers:

- ZIP fetch success returns the raw archive bytes.
- ZIP parse extracts per-job text from top-level ``<n>_<name>.txt`` entries.
- ZIP 404 routes through the per-job text endpoint fallback.
- 401 / 403 raise typed :class:`RestAuthError`.
- 5xx surfaces after the shared retry budget.
- Empty / malformed ZIP returns an empty dict (no crash).
"""

from __future__ import annotations

import io
import urllib.error
import zipfile
from typing import Any, Dict, List

import pytest

from yoke_core.domain import github_actions_logs
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestNotFoundError,
    RestServerError,
    RestTransportError,
)


def _build_zip(entries: Dict[str, str]) -> bytes:
    """Build an in-memory ZIP archive from ``{name: text}`` entries."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, body in entries.items():
            archive.writestr(name, body)
    return buf.getvalue()


class _FakeResponse:
    """``urlopen`` context-manager substitute that yields bytes."""

    def __init__(self, payload: bytes, status: int = 200) -> None:
        self._payload = payload
        self.status = status
        self.headers: Dict[str, str] = {}

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
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


class TestFetchFailedLogZip:
    def test_returns_bytes_on_success(self, monkeypatch):
        zip_bytes = _build_zip({"1_build.txt": "step output"})
        _install_urlopen(monkeypatch, [zip_bytes])

        result = github_actions_logs.fetch_failed_log_zip(
            "o/r", "123", token="ghs_test"
        )

        assert result == zip_bytes

    def test_empty_token_raises_auth_error(self):
        with pytest.raises(RestAuthError):
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token="")

    def test_401_raises_typed_auth_error(self, monkeypatch):
        _install_urlopen(monkeypatch, [_make_http_error(401, b"Bad credentials")])

        with pytest.raises(RestAuthError) as exc_info:
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token="ghs_x")

        assert exc_info.value.status == 401

    def test_403_raises_typed_auth_error(self, monkeypatch):
        _install_urlopen(monkeypatch, [_make_http_error(403, b"forbidden scope")])

        with pytest.raises(RestAuthError) as exc_info:
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token="ghs_x")

        assert exc_info.value.status == 403

    def test_404_raises_typed_not_found(self, monkeypatch):
        _install_urlopen(monkeypatch, [_make_http_error(404)])

        with pytest.raises(RestNotFoundError) as exc_info:
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token="ghs_x")

        assert exc_info.value.status == 404

    def test_5xx_retries_then_surfaces(self, monkeypatch):
        responses = [
            _make_http_error(500, b"upstream error"),
            _make_http_error(502, b"bad gateway"),
            _make_http_error(503, b"unavailable"),
        ]
        _install_urlopen(monkeypatch, responses)

        with pytest.raises(RestServerError) as exc_info:
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token="ghs_x")

        assert exc_info.value.status in (500, 502, 503)

    def test_5xx_then_success_returns_bytes(self, monkeypatch):
        zip_bytes = _build_zip({"1_test.txt": "passed"})
        responses = [_make_http_error(503), zip_bytes]
        _install_urlopen(monkeypatch, responses)

        result = github_actions_logs.fetch_failed_log_zip(
            "o/r", "123", token="ghs_x"
        )

        assert result == zip_bytes

    def test_no_token_in_error_text(self, monkeypatch):
        """NFR-3: typed errors must not echo the bearer token."""
        _install_urlopen(monkeypatch, [_make_http_error(401, b"Bad credentials")])
        secret = "ghs_secret_token_must_not_leak"

        with pytest.raises(RestAuthError) as exc_info:
            github_actions_logs.fetch_failed_log_zip("o/r", "123", token=secret)

        rendered = f"{exc_info.value} | body={exc_info.value.body}"
        assert secret not in rendered


class TestParseFailedLogZip:
    def test_extracts_top_level_entries(self):
        zip_bytes = _build_zip(
            {
                "1_build.txt": "build step output\n",
                "2_test.txt": "test step output\n",
            }
        )

        result = github_actions_logs.parse_failed_log_zip(zip_bytes)

        assert result == {
            "build": "build step output\n",
            "test": "test step output\n",
        }

    def test_skips_nested_step_files(self):
        zip_bytes = _build_zip(
            {
                "1_build.txt": "top-level\n",
                "build/1_setup.txt": "step level (skip)\n",
            }
        )

        result = github_actions_logs.parse_failed_log_zip(zip_bytes)

        assert "build" in result
        assert all("/" not in key for key in result)

    def test_tolerates_missing_numeric_prefix(self):
        zip_bytes = _build_zip({"build.txt": "no number prefix"})

        result = github_actions_logs.parse_failed_log_zip(zip_bytes)

        assert result == {"build": "no number prefix"}

    def test_empty_archive_returns_empty(self):
        zip_bytes = _build_zip({})

        result = github_actions_logs.parse_failed_log_zip(zip_bytes)

        assert result == {}

    def test_malformed_zip_returns_empty(self):
        result = github_actions_logs.parse_failed_log_zip(b"not a zip")

        assert result == {}

    def test_empty_bytes_returns_empty(self):
        assert github_actions_logs.parse_failed_log_zip(b"") == {}


class TestFetchFailedLog:
    def test_composes_fetch_and_parse(self, monkeypatch):
        import json

        zip_bytes = _build_zip(
            {"1_build.txt": "compile failed", "2_test.txt": "tests passed"}
        )
        _install_urlopen(monkeypatch, [zip_bytes])
        jobs_payload = {
            "jobs": [
                {"id": 10, "name": "build", "conclusion": "failure"},
                {"id": 11, "name": "test", "conclusion": "success"},
            ]
        }

        from yoke_core.domain import gh_rest_transport

        def _fake_rest_urlopen(request, timeout=None):
            return _FakeResponse(json.dumps(jobs_payload).encode("utf-8"))

        monkeypatch.setattr(gh_rest_transport, "urlopen", _fake_rest_urlopen)

        result = github_actions_logs.fetch_failed_log(
            "o/r", "123", token="ghs_x"
        )

        assert result == {"build": "compile failed"}

    def test_zip_404_falls_back_to_per_job(self, monkeypatch):
        # First call: GET /runs/{id}/logs → 404
        # Second call: GET /runs/{id}/jobs → JSON listing
        # Third call: GET /jobs/{job_id}/logs → bytes
        import json

        jobs_payload = {
            "jobs": [
                {"id": 999, "name": "build", "conclusion": "failure"},
                {"id": 1000, "name": "test", "conclusion": "success"},
            ]
        }

        # The rest_get for jobs listing goes through gh_rest_transport, which
        # has its own urlopen seam. We monkeypatch BOTH module seams here.
        from yoke_core.domain import gh_rest_transport

        outer_calls: List[str] = []
        outer_iter = iter(
            [
                _make_http_error(404),  # ZIP fetch
                b"build job log body\n",  # job 999 text
            ]
        )

        def _fake_logs_urlopen(request, timeout=None):
            outer_calls.append(
                request.full_url if hasattr(request, "full_url") else str(request)
            )
            payload = next(outer_iter)
            if isinstance(payload, Exception):
                raise payload
            return _FakeResponse(payload)

        monkeypatch.setattr(github_actions_logs, "urlopen", _fake_logs_urlopen)
        monkeypatch.setattr(github_actions_logs, "sleep", lambda _s: None)

        def _fake_rest_urlopen(request, timeout=None):
            return _FakeResponse(json.dumps(jobs_payload).encode("utf-8"))

        monkeypatch.setattr(gh_rest_transport, "urlopen", _fake_rest_urlopen)

        result = github_actions_logs.fetch_failed_log(
            "o/r", "123", token="ghs_x"
        )

        # Only the failed job's log should be present.
        assert result == {"build": "build job log body\n"}
        # ZIP endpoint + per-job text endpoint were both hit.
        assert any("/runs/123/logs" in c for c in outer_calls)
        assert any("/jobs/999/logs" in c for c in outer_calls)

    def test_zip_404_no_failed_jobs_returns_empty(self, monkeypatch):
        import json

        from yoke_core.domain import gh_rest_transport

        jobs_payload = {"jobs": [{"id": 1, "name": "ok", "conclusion": "success"}]}

        def _fake_logs_urlopen(request, timeout=None):
            raise _make_http_error(404)

        monkeypatch.setattr(github_actions_logs, "urlopen", _fake_logs_urlopen)
        monkeypatch.setattr(github_actions_logs, "sleep", lambda _s: None)

        def _fake_rest_urlopen(request, timeout=None):
            return _FakeResponse(json.dumps(jobs_payload).encode("utf-8"))

        monkeypatch.setattr(gh_rest_transport, "urlopen", _fake_rest_urlopen)

        result = github_actions_logs.fetch_failed_log(
            "o/r", "123", token="ghs_x"
        )

        assert result == {}
