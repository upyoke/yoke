"""Tests for github_pr_rest — pull-request create via REST.

The REST transport is mocked via ``urlopen`` monkeypatching — no live
network. Mirrors the fake-urlopen idiom in test_github_variables_rest.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from yoke_core.domain import github_pr_rest as mod
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestTransportError,
    RestUnprocessableError,
)


class _FakeResponse:
    def __init__(self, status: int, body: Any):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        self.headers = {"X-RateLimit-Remaining": "5000"}

    def read(self):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_error(code: int, message: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/repos/owner/repo/pulls",
        code=code,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(json.dumps({"message": message}).encode("utf-8")),
    )


def _install_fake_urlopen(monkeypatch, responses: list[Any]):
    """Install a fake urlopen serving ``responses`` FIFO; record each request."""
    received: list[dict] = []

    def fake(req, timeout=None):
        received.append({
            "method": req.get_method(),
            "url": req.full_url,
            "body": req.data,
        })
        if not responses:
            raise AssertionError("fake urlopen exhausted")
        nxt = responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    from yoke_core.domain import gh_rest_transport
    monkeypatch.setattr(gh_rest_transport, "urlopen", fake)
    return received


def test_create_pull_request_posts_minimal_payload(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(201, {
            "number": 7,
            "html_url": "https://github.com/owner/repo/pull/7",
        })],
    )

    outcome = mod.create_pull_request(
        "owner/repo", title="T", head="feature-x", base="main", token="t",
    )

    assert outcome == {
        "number": 7,
        "url": "https://github.com/owner/repo/pull/7",
    }
    assert len(received) == 1
    assert received[0]["method"] == "POST"
    assert received[0]["url"].endswith("/repos/owner/repo/pulls")
    body = json.loads(received[0]["body"].decode("utf-8"))
    # body key omitted when no description given.
    assert body == {"title": "T", "head": "feature-x", "base": "main",
                    "draft": False}


def test_create_pull_request_includes_body_and_draft(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(201, {"number": 8, "html_url": "https://x/pull/8"})],
    )

    mod.create_pull_request(
        "owner/repo", title="T", head="h", base="stage",
        body="## Summary\n\nDetails.", draft=True, token="t",
    )

    body = json.loads(received[0]["body"].decode("utf-8"))
    assert body == {
        "title": "T", "head": "h", "base": "stage",
        "draft": True, "body": "## Summary\n\nDetails.",
    }


def test_create_pull_request_propagates_auth_error(monkeypatch):
    _install_fake_urlopen(monkeypatch, [_http_error(401, "Bad credentials")])

    with pytest.raises(RestAuthError):
        mod.create_pull_request(
            "owner/repo", title="T", head="h", base="main", token="t",
        )


def test_create_pull_request_propagates_unprocessable(monkeypatch):
    # GitHub 422s when a PR for head->base already exists.
    _install_fake_urlopen(
        monkeypatch, [_http_error(422, "A pull request already exists")],
    )

    with pytest.raises(RestUnprocessableError):
        mod.create_pull_request(
            "owner/repo", title="T", head="h", base="main", token="t",
        )


def test_create_pull_request_missing_number_raises(monkeypatch):
    _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(201, {"html_url": "https://x/pull/9"})],
    )

    with pytest.raises(RestTransportError, match="missing pull-request number"):
        mod.create_pull_request(
            "owner/repo", title="T", head="h", base="main", token="t",
        )
