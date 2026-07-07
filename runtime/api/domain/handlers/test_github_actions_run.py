"""Tests for the ``github_actions.wait_run`` handler."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_core.domain.handlers import github_actions_run
from yoke_core.domain.handlers.github_actions_run import (
    _classify,
    handle_run_get,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghp_test_token",
    env={"PATH": "/usr/bin", "GH_TOKEN": "ghp_test_token"},
)


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke", "run_id": "123"}
    return FunctionCallRequest(
        function="github_actions.wait_run",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project: _RESOLVED,
    )


class TestClassify:
    def test_completed_success(self):
        payload = github_actions_run.RunGetRequest(repo="o/r", run_id="123")
        out = _classify(
            payload,
            {"id": 123, "status": "completed", "conclusion": "success"},
        )
        assert out.state == "success"
        assert out.message == "success"

    def test_completed_failure(self):
        payload = github_actions_run.RunGetRequest(repo="o/r", run_id="123")
        out = _classify(
            payload,
            {"id": 123, "status": "completed", "conclusion": "failure"},
        )
        assert out.state == "failed"
        assert out.message == "failed:failure"

    def test_running_statuses(self):
        payload = github_actions_run.RunGetRequest(repo="o/r", run_id="123")
        assert _classify(payload, {"status": "queued"}).state == "waiting"
        assert _classify(payload, {"status": "pending"}).state == "waiting"
        assert _classify(payload, {"status": "waiting"}).state == "waiting"
        assert _classify(payload, {"status": "in_progress"}).state == "running"


class TestHandleRunGet:
    def test_returns_single_run_state(self, monkeypatch):
        calls = []

        def fake_rest_get(path, *, token):
            calls.append((path, token))
            return {
                "id": 123,
                "status": "in_progress",
                "conclusion": None,
                "html_url": "https://github.com/o/r/actions/runs/123",
            }

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", fake_rest_get,
        )
        outcome = handle_run_get(_make_request({"repo": "o/r", "run_id": "123"}))

        assert outcome.primary_success is True
        assert outcome.result_payload["state"] == "running"
        assert outcome.result_payload["message"] == "in_progress"
        assert calls == [("/repos/o/r/actions/runs/123", "ghp_test_token")]

    def test_rejects_non_global_target(self):
        outcome = handle_run_get(_make_request(target_kind="item"))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_rejects_repo_without_slash(self):
        outcome = handle_run_get(_make_request({"repo": "no-slash", "run_id": "1"}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_transport_error_surfaces(self, monkeypatch):
        from yoke_core.domain.gh_rest_transport import RestServerError

        def fake_rest_get(path, *, token):
            raise RestServerError("HTTP 503: brief outage", status=503)

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", fake_rest_get,
        )
        outcome = handle_run_get(_make_request())
        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"

    def test_registration_entry_present(self):
        ids = {entry["function_id"] for entry in github_actions_run.REGISTRATIONS}
        assert "github_actions.wait_run" in ids
        entry = github_actions_run.REGISTRATIONS[0]
        assert entry["side_effects"] == []
        assert entry["target_kinds"] == ["global"]
