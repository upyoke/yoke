"""Tests for the PAT-driven GitHub REST transport."""

from __future__ import annotations

import http.client
import io
import json
import urllib.error
from typing import Any

import pytest

from yoke_core.domain import gh_rest_transport as t


# ---------------------------------------------------------------------------
# Fixtures and fakes
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Mimic the urlopen() context-manager return value."""

    def __init__(self, *, status: int, body: bytes, headers: dict[str, str] | None = None):
        self.status = status
        self._body = body
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def read(self) -> bytes:
        return self._body


def _make_http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    err = urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=status,
        msg=f"HTTP {status}",
        hdrs={"Content-Type": "application/json"},  # type: ignore[arg-type]
        fp=io.BytesIO(body),
    )
    return err


@pytest.fixture(autouse=True)
def _reset_module(monkeypatch):
    """Ensure each test gets a fresh urlopen + sleep + env var state."""
    monkeypatch.setattr(t, "sleep", lambda _s: None)
    monkeypatch.delenv(t._FAKE_DIR_ENV, raising=False)
    yield


# ---------------------------------------------------------------------------
# Auth wiring
# ---------------------------------------------------------------------------


def test_auth_header_includes_pat(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["headers"] = dict(request.header_items())
        seen["body"] = request.data
        return _FakeResponse(status=200, body=b'{"id": 1}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)

    req = t.RestRequest(method="get", path="/repos/o/r/pulls/1")
    resp = t.request_with_retry(req, token="ghp_xyz")
    assert resp.status == 200
    assert resp.body == {"id": 1}
    assert seen["url"] == "https://api.github.com/repos/o/r/pulls/1"
    assert seen["method"] == "GET"
    # urllib normalises header names to title-case.
    headers_lower = {k.lower(): v for k, v in seen["headers"].items()}
    assert headers_lower["authorization"] == "Bearer ghp_xyz"
    assert headers_lower["accept"] == "application/vnd.github+json"
    assert headers_lower["x-github-api-version"] == t.GITHUB_API_VERSION


def test_missing_token_raises_auth(monkeypatch):
    with pytest.raises(t.RestAuthError):
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="")


def test_test_guard_blocks_default_network_transport(monkeypatch):
    monkeypatch.setenv("YOKE_TEST_BLOCK_LIVE_REST", "1")
    monkeypatch.setattr(t, "urlopen", t.urllib.request.urlopen)
    with pytest.raises(RuntimeError, match="live GitHub REST call"):
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_x")


def test_post_body_encoded_as_json(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["body"] = request.data
        seen["content_type"] = request.get_header("Content-type")
        return _FakeResponse(status=201, body=b'{"number": 17}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    payload = {"title": "x", "head": "b", "base": "main", "body": "auto"}
    resp = t.request_with_retry(
        t.RestRequest(method="POST", path="/repos/o/r/pulls", body=payload),
        token="ghp_xyz",
    )
    assert resp.body == {"number": 17}
    assert json.loads(seen["body"].decode()) == payload
    assert seen["content_type"] == "application/json"


def test_query_string_encoded(monkeypatch):
    seen: dict[str, Any] = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        return _FakeResponse(status=200, body=b"[]")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(
        t.RestRequest(
            method="GET",
            path="/repos/o/r/pulls",
            query={"head": "o:branch", "state": "open"},
        ),
        token="ghp_xyz",
    )
    assert "head=o%3Abranch" in seen["url"]
    assert "state=open" in seen["url"]


# ---------------------------------------------------------------------------
# Every retry matcher fires for synthetic responses
# ---------------------------------------------------------------------------


def test_retries_on_502(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(502, b"Bad Gateway")
        return _FakeResponse(status=200, body=b'{"ok": true}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    resp = t.request_with_retry(
        t.RestRequest(method="GET", path="/x"), token="ghp_xyz"
    )
    assert resp.body == {"ok": True}
    assert calls["n"] == 2


def test_retries_on_429_rate_limit(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(429, b"rate limit exceeded")
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_xyz")
    assert calls["n"] == 2


def test_retries_on_503(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(503, b"Service Unavailable")
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_xyz")
    assert calls["n"] == 2


def test_retries_on_422_with_graphql_propagation_body(monkeypatch):
    """422 alone is not retryable, but 422 with a propagation-race body is."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _make_http_error(
                422, b'{"message": "Could not resolve to a PullRequest"}'
            )
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_xyz")
    assert calls["n"] == 2


def test_422_without_retryable_body_terminal(monkeypatch):
    def fake_urlopen(request, timeout):
        raise _make_http_error(
            422, b'{"message": "A pull request already exists"}'
        )

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestUnprocessableError) as excinfo:
        t.request_with_retry(
            t.RestRequest(method="POST", path="/repos/o/r/pulls", body={"head": "b"}),
            token="ghp_xyz",
        )
    assert excinfo.value.status == 422
    assert "already exists" in (excinfo.value.body or "")


def test_retries_on_200_with_base_branch_modified_envelope(monkeypatch):
    """AC-7: PUT /pulls/{n}/merge returns 200 with a retryable error envelope."""
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            body = json.dumps(
                {"message": "Base branch was modified. Review and try the merge again."}
            ).encode()
            return _FakeResponse(status=200, body=body)
        return _FakeResponse(status=200, body=b'{"merged": true}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    resp = t.request_with_retry(
        t.RestRequest(
            method="PUT",
            path="/repos/o/r/pulls/1/merge",
            body={"merge_method": "merge"},
        ),
        token="ghp_xyz",
    )
    assert resp.body == {"merged": True}
    assert calls["n"] == 2


def test_persistent_base_branch_modified_exhausts_retries(monkeypatch):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        body = json.dumps(
            {"message": "Base branch was modified. Review and try the merge again."}
        ).encode()
        return _FakeResponse(status=200, body=body)

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestUnprocessableError):
        t.request_with_retry(
            t.RestRequest(method="PUT", path="/repos/o/r/pulls/1/merge"),
            token="ghp_xyz",
        )
    assert calls["n"] == 3  # MAX_RETRIES


def test_network_error_retries(monkeypatch, capsys):
    calls = {"n": 0}

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            raise urllib.error.URLError("timed out")
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_xyz")
    assert calls["n"] == 2
    assert (
        "GitHub REST retry 1/3 after network failure: timed out"
        in capsys.readouterr().err
    )


def test_response_read_error_retries(monkeypatch):
    calls = {"n": 0}

    class BrokenRead(_FakeResponse):
        def read(self) -> bytes:
            raise http.client.IncompleteRead(b"partial", 10)

    def fake_urlopen(request, timeout):
        calls["n"] += 1
        if calls["n"] < 2:
            return BrokenRead(status=200, body=b"")
        return _FakeResponse(status=200, body=b"{}")

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    t.request_with_retry(t.RestRequest(method="GET", path="x"), token="ghp_xyz")
    assert calls["n"] == 2


# ---------------------------------------------------------------------------
# Terminal auth / not-found
# ---------------------------------------------------------------------------


def test_401_is_terminal_auth_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise _make_http_error(401, b'{"message":"Bad credentials"}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestAuthError) as excinfo:
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_x")
    assert excinfo.value.status == 401


def test_403_is_terminal_auth_error(monkeypatch):
    """A 403 WITHOUT the rate-limit body markers is a terminal auth error."""
    def fake_urlopen(request, timeout):
        raise _make_http_error(403, b'{"message":"Resource not accessible"}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestAuthError):
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_x")


# Rate-limit recognition tests (429 + 403-with-rate-limit-body) live in
# the sibling file: test_gh_rest_transport_rate_limit.py.


def test_404_is_terminal_not_found(monkeypatch):
    def fake_urlopen(request, timeout):
        raise _make_http_error(404, b'{"message":"Not Found"}')

    monkeypatch.setattr(t, "urlopen", fake_urlopen)
    with pytest.raises(t.RestNotFoundError):
        t.request_with_retry(t.RestRequest(method="GET", path="/x"), token="ghp_x")


# Helpers and test-seam coverage live in test_gh_rest_transport_seam.py.
