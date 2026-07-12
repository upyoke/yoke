"""REST-transport coverage for github_actions: helpers + ``check-ci`` matrix.

Sibling to ``test_github_actions.py``. The subcommand tests (poll,
wait_run, find_run, failed_log) import ``_fake_urls`` / ``_RESOLVED`` /
``_raise_error`` from this module to keep the urlopen fixture in one
place.
"""

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


class TestResolveToken:
    def test_returns_token_on_success(self, _resolver_ok):
        assert (
            github_actions_rest.resolve_token(
                "yoke",
                "o/r",
                required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
            )
            == "ghs_test_token"
        )
        assert _resolver_ok == [
            (
                "yoke",
                {"required_permissions": GITHUB_ACTIONS_READ_PERMISSION_LEVELS},
            )
        ]

    def test_exits_4_when_repo_does_not_match_binding(
        self,
        _resolver_ok,
        capsys,
    ):
        with pytest.raises(SystemExit) as exc_info:
            github_actions_rest.resolve_token(
                "yoke",
                "other/repo",
                required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
            )
        assert exc_info.value.code == 4
        err = capsys.readouterr().err
        assert "repository_binding_mismatch" in err
        assert "o/r" in err

    def test_exits_4_on_missing_app_credentials(self, monkeypatch, capsys):
        monkeypatch.setattr(
            github_actions_rest,
            "resolve_project_github_auth",
            _raise_error(MissingAppCredentials),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions_rest.resolve_token(
                "yoke",
                "o/r",
                required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
            )
        assert exc_info.value.code == 4
        err = capsys.readouterr().err
        assert "missing_app_credentials" in err and "Repair:" in err

    def test_exits_4_on_missing_capability_with_repair_hint(self, monkeypatch, capsys):
        monkeypatch.setattr(
            github_actions_rest,
            "resolve_project_github_auth",
            _raise_error(MissingCapability),
        )
        with pytest.raises(SystemExit) as exc_info:
            github_actions_rest.resolve_token(
                "yoke",
                "o/r",
                required_permissions=GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
            )
        assert exc_info.value.code == 4
        err = capsys.readouterr().err
        assert "missing_capability" in err and "github-binding bind" in err


class TestLatestWorkflowRun:
    """Direct coverage of the helper that ``executors.py`` consumes."""

    def test_returns_first_run_dict(self, monkeypatch):
        payload = {
            "workflow_runs": [
                {
                    "id": 12345,
                    "status": "completed",
                    "conclusion": "success",
                    "created_at": "2026-04-11T00:00:00Z",
                    "head_sha": "abc123",
                    "html_url": "https://github.com/o/r/actions/runs/12345",
                }
            ]
        }
        with _fake_urls(monkeypatch, [payload]) as calls:
            result = github_actions_rest.latest_workflow_run(
                "o/r", "deploy.yml", branch="main", token="ghs_x"
            )
        assert result is not None
        assert result["id"] == 12345
        assert result["status"] == "completed"
        assert result["conclusion"] == "success"
        # branch filter is applied via query string.
        assert "branch=main" in calls[0]

    def test_returns_none_on_empty_runs(self, monkeypatch):
        with _fake_urls(monkeypatch, [{"workflow_runs": []}]):
            result = github_actions_rest.latest_workflow_run(
                "o/r", "deploy.yml", branch="main", token="ghs_x"
            )
        assert result is None

    def test_propagates_rest_error(self, monkeypatch):
        import urllib.error

        err = urllib.error.HTTPError(
            "https://example/foo",
            500,
            "boom",
            {},
            None,  # type: ignore[arg-type]
        )
        # Repeat error so retries exhaust; transport then surfaces it.
        with _fake_urls(monkeypatch, [err, err, err]):
            from yoke_core.domain import gh_rest_transport

            monkeypatch.setattr(gh_rest_transport, "sleep", lambda _s: None)
            with pytest.raises(RestServerError):
                github_actions_rest.latest_workflow_run(
                    "o/r", "deploy.yml", branch="main", token="ghs_x"
                )

    def test_rejects_malformed_response(self, monkeypatch):
        with _fake_urls(monkeypatch, [{}]):
            with pytest.raises(RestTransportError, match="omitted workflow_runs"):
                github_actions_rest.latest_workflow_run(
                    "o/r", "deploy.yml", branch="main", token="ghs_x"
                )


class TestRestHelpers:
    def test_get_returns_parsed_body(self, monkeypatch):
        with _fake_urls(monkeypatch, [{"status": "completed"}]):
            data = github_actions_rest.rest_get(
                "/repos/o/r/actions/runs/1", token="ghs_x"
            )
        assert data == {"status": "completed"}

    def test_get_returns_none_on_404(self, monkeypatch):
        import urllib.error

        err = urllib.error.HTTPError(
            "https://example/foo",
            404,
            "Not Found",
            {},
            None,  # type: ignore[arg-type]
        )
        with _fake_urls(monkeypatch, [err]):
            data = github_actions_rest.rest_get("/repos/o/r/missing", token="ghs_x")
        assert data is None

    def test_post_dispatches_body(self, monkeypatch):
        with _fake_urls(monkeypatch, [""]) as calls:
            github_actions_rest.rest_post(
                "/repos/o/r/actions/workflows/ci.yml/dispatches",
                body={"ref": "main"},
                token="ghs_x",
            )
        assert calls and "/actions/workflows/ci.yml/dispatches" in calls[0]
