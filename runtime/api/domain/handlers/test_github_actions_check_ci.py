"""Tests for the ``github_actions.check_ci`` handler."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_core.domain.handlers import github_actions_check_ci
from yoke_core.domain.handlers.github_actions_check_ci import (
    CheckCiResponse,
    _classify,
    handle_check_ci,
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
    token="ghs_test_token",
    env={"PATH": "/usr/bin", "GH_TOKEN": "ghs_test_token"},
)


def _make_request(payload: Optional[Dict[str, Any]] = None,
                  *, target_kind: str = "global") -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke", "workflow": "ci.yml"}
    return FunctionCallRequest(
        function="github_actions.check_ci",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture
def _resolver_ok(monkeypatch):
    from yoke_core.domain.handlers import github_actions_check_ci as h
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )
    return h


class TestClassify:
    def test_no_runs_when_none(self):
        assert _classify(None).state == "no_runs"

    def test_no_runs_when_missing_id(self):
        assert _classify({"status": "completed"}).state == "no_runs"

    def test_completed_success(self):
        out = _classify(
            {"id": 1, "status": "completed", "conclusion": "success",
             "html_url": "https://x"}
        )
        assert out.state == "passed"
        assert out.run_id == 1
        assert out.html_url == "https://x"

    def test_completed_failure(self):
        out = _classify(
            {"id": 1, "status": "completed", "conclusion": "failure"}
        )
        assert out.state == "failed"
        assert out.conclusion == "failure"

    def test_in_progress(self):
        out = _classify({"id": 1, "status": "in_progress"})
        assert out.state == "running"

    def test_queued_collapses_into_running(self):
        out = _classify({"id": 1, "status": "queued"})
        assert out.state == "running"

    def test_pending_treated_as_running(self):
        out = _classify({"id": 1, "status": "pending"})
        assert out.state == "running"


class TestHandle:
    def test_rejects_non_global_target(self):
        outcome = handle_check_ci(_make_request(target_kind="item"))
        assert not outcome.primary_success
        assert outcome.error and outcome.error.code == "invalid_payload"

    def test_rejects_missing_repo(self):
        outcome = handle_check_ci(_make_request({"workflow": "ci.yml"}))
        assert not outcome.primary_success

    def test_rejects_repo_without_slash(self):
        outcome = handle_check_ci(
            _make_request({"repo": "no-slash", "workflow": "ci.yml"})
        )
        assert not outcome.primary_success
        assert "owner/name" in outcome.error.message

    def test_returns_passed(self, monkeypatch, _resolver_ok):
        run = {"id": 42, "status": "completed", "conclusion": "success",
               "html_url": "https://x"}
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: run,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "passed"
        assert outcome.result_payload["run_id"] == 42

    def test_returns_failed_on_red(self, monkeypatch, _resolver_ok):
        run = {"id": 42, "status": "completed", "conclusion": "failure"}
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: run,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "failed"

    def test_returns_no_runs_when_empty(self, monkeypatch, _resolver_ok):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda *a, **kw: None,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "no_runs"

    def test_missing_token_surfaces_as_auth_error(self, monkeypatch):
        from yoke_core.domain.project_github_auth import MissingToken

        def _raise(project, **kw):
            raise MissingToken(project, "token missing")

        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            _raise,
        )
        outcome = handle_check_ci(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "project_auth_error"

    def test_transport_error_surfaces(self, monkeypatch, _resolver_ok):
        from yoke_core.domain.gh_rest_transport import RestServerError

        def _raise(*a, **kw):
            raise RestServerError("HTTP 503: brief outage", status=503)

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            _raise,
        )
        outcome = handle_check_ci(_make_request())
        assert not outcome.primary_success
        assert outcome.error.code == "rest_transport_error"


class TestSingleShot:
    """The handler is single-shot: wait semantics live in the CLI adapter
    (field-note 12612 — a server-side wait loop exceeds the https relay
    read timeout)."""

    def test_running_returns_immediately_one_rest_read(
        self, monkeypatch, _resolver_ok,
    ):
        calls = []

        def fake(*a, **kw):
            calls.append(1)
            return {"id": 7, "status": "in_progress"}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run", fake,
        )
        outcome = handle_check_ci(_make_request())
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "running"
        assert calls == [1]

    def test_legacy_wait_keys_are_ignored_not_looped(
        self, monkeypatch, _resolver_ok,
    ):
        # Founder cutover: older payloads carrying wait/timeout_sec get
        # the point-in-time answer (extra fields ignored), never a loop.
        calls = []

        def fake(*a, **kw):
            calls.append(1)
            return {"id": 7, "status": "queued"}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run", fake,
        )
        outcome = handle_check_ci(_make_request(
            {"repo": "o/r", "workflow": "ci.yml", "wait": True,
             "timeout_sec": 600}
        ))
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "running"
        assert calls == [1]


class TestRegistration:
    def test_registration_entry_present(self):
        ids = {entry["function_id"] for entry in
               github_actions_check_ci.REGISTRATIONS}
        assert "github_actions.check_ci" in ids
