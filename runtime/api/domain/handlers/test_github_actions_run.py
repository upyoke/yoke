"""Tests for the ``github_actions.wait_run`` handler."""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers import github_actions_run
from yoke_core.domain.handlers.github_actions_run import (
    _classify,
    handle_run_get,
)
from yoke_core.domain.github_actions_run_stall import (
    PENDING_ZERO_JOBS_STALL_SECONDS,
    PENDING_ZERO_JOBS_STALL_REASON,
    STALLED_DISPATCH_TOKEN,
    pending_run_message,
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
)


def _make_request(
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
    include_project: bool = True,
) -> FunctionCallRequest:
    if payload is None:
        payload = {"repo": "upyoke/yoke", "run_id": "123"}
    payload = dict(payload)
    if include_project:
        payload.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.wait_run",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


@pytest.fixture(autouse=True)
def _auth_resolved(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _RESOLVED

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        _resolve,
    )
    return calls


class TestClassify:
    def test_completed_success(self):
        payload = github_actions_run.RunGetRequest(
            repo="o/r", run_id="123", project="yoke",
        )
        out = _classify(
            payload,
            {"id": 123, "status": "completed", "conclusion": "success"},
        )
        assert out.state == "success"
        assert out.message == "success"

    def test_completed_failure(self):
        payload = github_actions_run.RunGetRequest(
            repo="o/r", run_id="123", project="yoke",
        )
        out = _classify(
            payload,
            {"id": 123, "status": "completed", "conclusion": "failure"},
        )
        assert out.state == "failed"
        assert out.message == "failed:failure"

    def test_running_statuses(self):
        payload = github_actions_run.RunGetRequest(
            repo="o/r", run_id="123", project="yoke",
        )
        assert _classify(payload, {"status": "queued"}).state == "waiting"
        assert _classify(payload, {"status": "pending"}).state == "waiting"
        assert _classify(payload, {"status": "waiting"}).state == "waiting"
        assert _classify(payload, {"status": "in_progress"}).state == "running"

    def test_stale_pending_zero_jobs_names_the_stall_and_recovery(self):
        observed = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)
        updated = observed - timedelta(seconds=PENDING_ZERO_JOBS_STALL_SECONDS + 1)

        message = pending_run_message(
            repo="upyoke/yoke",
            run_id="123",
            jobs_count=0,
            updated_at=updated.isoformat(),
            observed_at=observed,
        )

        assert STALLED_DISPATCH_TOKEN in message
        assert f"waiting_on={PENDING_ZERO_JOBS_STALL_REASON}" in message
        assert "repos/upyoke/yoke/actions/runs/123/force-cancel" in message


class TestHandleRunGet:
    def test_rejects_missing_project(self):
        outcome = handle_run_get(_make_request(include_project=False))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_returns_single_run_state(self, monkeypatch, _auth_resolved):
        calls = []

        def fake_rest_get(path, *, token):
            calls.append((path, token))
            return {
                "id": 123,
                "status": "in_progress",
                "conclusion": None,
                "html_url": "https://github.com/upyoke/yoke/actions/runs/123",
            }

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", fake_rest_get,
        )
        outcome = handle_run_get(_make_request({
            "repo": "upyoke/yoke", "run_id": "123",
        }))

        assert outcome.primary_success is True
        assert outcome.result_payload["state"] == "running"
        assert outcome.result_payload["message"] == "in_progress"
        assert calls == [
            ("/repos/upyoke/yoke/actions/runs/123", "ghs_test_token")
        ]
        assert _auth_resolved == [
            (
                "yoke",
                {"required_permissions": GITHUB_ACTIONS_READ_PERMISSION_LEVELS},
            )
        ]

    def test_rejects_non_global_target(self):
        outcome = handle_run_get(_make_request(target_kind="item"))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_pending_run_includes_job_count_and_updated_at(
        self,
        monkeypatch,
    ):
        calls = []

        def fake_rest_get(path, *, token):
            calls.append(path)
            if path.endswith("/attempts/2/jobs"):
                return {"total_count": 0, "jobs": []}
            return {
                "id": 123,
                "status": "pending",
                "run_attempt": 2,
                "updated_at": "2999-01-01T00:00:00Z",
            }

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", fake_rest_get,
        )
        outcome = handle_run_get(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["jobs_count"] == 0
        assert outcome.result_payload["updated_at"] == "2999-01-01T00:00:00Z"
        assert outcome.result_payload["message"].startswith("pending run=123")
        assert calls[-1].endswith("/actions/runs/123/attempts/2/jobs")

    def test_rejects_repo_without_slash(self):
        outcome = handle_run_get(_make_request({"repo": "no-slash", "run_id": "1"}))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"

    def test_transport_error_surfaces(self, monkeypatch):
        from yoke_core.domain.gh_rest_transport import RestServerError

        def fake_rest_get(path, *, token):
            raise RestServerError("HTTP 503: brief outage", status=503)

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            fake_rest_get,
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
