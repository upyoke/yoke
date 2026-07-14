"""Tests for github_variables_rest — repo variable upsert via REST.

The REST transport is mocked via ``urlopen`` monkeypatching — no live
network. Mirrors the fake-urlopen idiom in test_github_secrets_rest.
"""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from yoke_core.domain import github_variables_rest as mod
from yoke_core.domain.gh_rest_transport import RestAuthError, RestNotFoundError


class _FakeResponse:
    def __init__(self, status: int, body: Any):
        self.status = status
        self._body = (
            body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        )
        self.headers = {"X-RateLimit-Remaining": "5000"}

    def read(self, _size: int = -1):
        return self._body

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _http_error(code: int, message: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://api.github.com/repos/owner/repo/actions/variables/X",
        code=code,
        msg=message,
        hdrs=None,
        fp=io.BytesIO(json.dumps({"message": message}).encode("utf-8")),
    )


def _install_fake_urlopen(monkeypatch, responses: list[Any]):
    """Install a fake urlopen serving ``responses`` FIFO; record each request."""
    received: list[dict] = []

    def fake(req, timeout=None):
        received.append(
            {
                "method": req.get_method(),
                "url": req.full_url,
                "body": req.data,
            }
        )
        if not responses:
            raise AssertionError("fake urlopen exhausted")
        nxt = responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    from yoke_core.domain import gh_rest_transport

    monkeypatch.setattr(gh_rest_transport, "urlopen", fake)
    return received


def test_set_repo_variable_patches_existing(monkeypatch):
    received = _install_fake_urlopen(monkeypatch, [_FakeResponse(204, b"")])

    outcome = mod.set_repo_variable(
        "owner/repo", "GATE", "false", token="ghs_variables_transport_test"
    )

    assert outcome == "updated"
    assert len(received) == 1
    assert received[0]["method"] == "PATCH"
    assert "/repos/owner/repo/actions/variables/GATE" in received[0]["url"]
    body = json.loads(received[0]["body"].decode("utf-8"))
    assert body == {"name": "GATE", "value": "false"}


def test_set_repo_variable_creates_on_404(monkeypatch):
    received = _install_fake_urlopen(
        monkeypatch,
        [
            _http_error(404, "Not Found"),
            _FakeResponse(201, {"name": "GATE", "value": "true"}),
        ],
    )

    outcome = mod.set_repo_variable(
        "owner/repo", "GATE", "true", token="ghs_variables_transport_test"
    )

    assert outcome == "created"
    assert len(received) == 2
    patch_req, post_req = received
    assert patch_req["method"] == "PATCH"
    assert post_req["method"] == "POST"
    assert post_req["url"].endswith("/repos/owner/repo/actions/variables")
    body = json.loads(post_req["body"].decode("utf-8"))
    assert body == {"name": "GATE", "value": "true"}


def test_set_repo_variable_propagates_auth_error(monkeypatch):
    _install_fake_urlopen(monkeypatch, [_http_error(401, "Bad credentials")])

    with pytest.raises(RestAuthError):
        mod.set_repo_variable(
            "owner/repo", "GATE", "x", token="ghs_variables_transport_test"
        )


def test_set_repo_variable_404_on_create_propagates(monkeypatch):
    # PATCH 404 (variable missing) then POST 404 (repo missing) -> raises.
    _install_fake_urlopen(
        monkeypatch,
        [_http_error(404, "Not Found"), _http_error(404, "Not Found")],
    )

    with pytest.raises(RestNotFoundError):
        mod.set_repo_variable(
            "owner/missing", "GATE", "x", token="ghs_variables_transport_test"
        )


def test_delete_repo_variable_uses_delete(monkeypatch):
    received = _install_fake_urlopen(monkeypatch, [_FakeResponse(204, b"")])
    mod.delete_repo_variable("owner/repo", "OLD", token="ghs_delete_test")
    assert received[0]["method"] == "DELETE"
    assert received[0]["url"].endswith("/repos/owner/repo/actions/variables/OLD")


@pytest.mark.parametrize("name", ["../secrets/X", "A/B", "-BAD", "A%2FB"])
def test_variable_set_get_delete_reject_path_injection(name):
    for operation in (
        lambda: mod.set_repo_variable("owner/repo", name, "x", token="unused"),
        lambda: mod.get_repo_variable("owner/repo", name, token="unused"),
        lambda: mod.delete_repo_variable("owner/repo", name, token="unused"),
    ):
        with pytest.raises(ValueError, match="config name"):
            operation()
