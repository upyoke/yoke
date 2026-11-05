# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from contextlib import contextmanager

from typing import Any, Dict, List

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)

from yoke_core.domain import (
    github_actions_rest,
)

from yoke_core.domain.gh_rest_transport import RestServerError, RestTransportError

from yoke_core.domain.project_github_auth import (
    MissingAppCredentials,
    MissingCapability,
    ProjectGithubAuth,
)

_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="o/r",
    token="ghs_test_token",
)


def _raise_error(error_cls):
    def _raise(project, **kw):
        raise error_cls(project, f"project '{project}' synthetic test failure")

    return _raise


class _FakeResponse:
    """Minimal urlopen() context-manager substitute for REST transport tests."""

    def __init__(self, body: Any, status: int = 200) -> None:
        if isinstance(body, (dict, list)):
            self._bytes = json.dumps(body).encode("utf-8")
        elif body is None:
            self._bytes = b""
        else:
            self._bytes = str(body).encode("utf-8")
        self.status = status
        self.headers: Dict[str, str] = {}

    def read(self, _size: int = -1) -> bytes:
        return self._bytes

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None


@contextmanager
def _fake_urls(monkeypatch, responses: List[Any]):
    """Yield a list that records every URL urlopen() was called with."""
    calls: List[str] = []
    iterator = iter(responses)

    def _fake_urlopen(req, timeout=None):
        calls.append(req.full_url if hasattr(req, "full_url") else str(req))
        try:
            result = next(iterator)
        except StopIteration:  # pragma: no cover - test misuse
            raise AssertionError("urlopen called more times than fixture allowed")
        if isinstance(result, Exception):
            raise result
        return _FakeResponse(result)

    from yoke_core.domain import gh_rest_transport

    monkeypatch.setattr(gh_rest_transport, "urlopen", _fake_urlopen)
    yield calls


@pytest.fixture
def _resolver_ok(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _RESOLVED

    monkeypatch.setattr(
        github_actions_rest,
        "resolve_project_github_auth",
        _resolve,
    )
    return calls
