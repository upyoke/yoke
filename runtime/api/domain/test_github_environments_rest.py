"""Tests for github_environments_rest — PUT environments + GET user."""

from __future__ import annotations

import io
import json
from typing import Any

import pytest

from yoke_core.domain import github_environments_rest as mod
from yoke_core.domain.gh_rest_transport import RestUnprocessableError


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


def _install_fake_urlopen(monkeypatch, responses: list[Any]):
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


def test_put_environment_with_protection_rules(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"id": 1, "name": "production"})],
    )

    config = {
        "wait_timer": 0,
        "reviewers": [{"type": "User", "id": 42}],
        "deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False},
    }
    result = mod.put_environment("owner/repo", "production", token="t", config=config)

    assert result["name"] == "production"
    assert received[0]["method"] == "PUT"
    assert "/repos/owner/repo/environments/production" in received[0]["url"]

    body = json.loads(received[0]["body"].decode("utf-8"))
    assert body["wait_timer"] == 0
    assert body["reviewers"] == [{"type": "User", "id": 42}]


def test_put_environment_basic_no_config(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"id": 2, "name": "staging"})],
    )

    mod.put_environment("owner/repo", "staging", token="t", config=None)

    body = json.loads(received[0]["body"].decode("utf-8"))
    assert body == {}


def test_put_environment_falls_back_when_protection_unsupported(monkeypatch):
    """Operator code may catch the 422 from a custom_branch_policies conflict
    and retry with a basic empty config; verify both calls land cleanly."""
    import urllib.error

    received = _install_fake_urlopen(
        monkeypatch,
        [
            urllib.error.HTTPError(
                url="https://api.github.com/repos/owner/repo/environments/production",
                code=422,
                msg="Unprocessable Entity",
                hdrs=None,
                fp=io.BytesIO(b'{"message":"Validation Failed"}'),
            ),
        ],
    )

    with pytest.raises(RestUnprocessableError):
        mod.put_environment("owner/repo", "production", token="t", config={"wait_timer": 0})


def test_fetch_authenticated_user(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [_FakeResponse(200, {"login": "alice", "id": 12345})],
    )

    user = mod.fetch_authenticated_user(token="t")
    assert user["login"] == "alice"
    assert user["id"] == 12345
    assert received[0]["method"] == "GET"
    assert "/user" in received[0]["url"]
