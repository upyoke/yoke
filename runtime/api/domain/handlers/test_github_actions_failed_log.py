"""Tests for the ``github_actions.failed_log`` handler."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.github_actions_failed_jobs import LOG_AVAILABLE, FailedJob
from yoke_core.domain.handlers.github_actions_failed_log import handle_failed_log
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_RESOLVED = ProjectGithubAuth(
    project="yoke",
    repo="upyoke/yoke",
    token="ghs_test_token",
)


def _make_request(payload: Dict[str, Any] | None = None) -> FunctionCallRequest:
    body = {"repo": "upyoke/yoke", "project": "yoke", "run_id": "123"}
    if payload is not None:
        body = dict(payload)
        body.setdefault("project", "yoke")
    return FunctionCallRequest(
        function="github_actions.failed_log",
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind="global"),
        payload=body,
    )


@pytest.fixture
def _resolver_ok(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        lambda project, **kw: _RESOLVED,
    )


def _failed_job(name: str, body: str, job_id: str = "900") -> FailedJob:
    return FailedJob(
        job_id=job_id,
        name=name,
        conclusion="failure",
        html_url=f"https://github.com/upyoke/yoke/actions/runs/123/job/{job_id}",
        log_text=body,
        log_status=LOG_AVAILABLE,
        log_detail="",
    )


def _stub_collect(monkeypatch, jobs):
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_failed_jobs.collect_failed_jobs",
        lambda repo, run_id, *, token: list(jobs),
    )


class TestHandleFailedLog:
    def test_reports_every_failed_job_with_identity(self, _resolver_ok, monkeypatch):
        _stub_collect(
            monkeypatch,
            [
                _failed_job("shard 6", "shard 6 boom", job_id="901"),
                _failed_job("shard 7", "shard 7 boom", job_id="902"),
            ],
        )

        outcome = handle_failed_log(_make_request())

        assert outcome.primary_success is True
        payload = outcome.result_payload
        assert payload["run_id"] == "123"
        assert payload["failed_job_count"] == 2
        assert payload["logs_available_count"] == 2
        assert [job["job_id"] for job in payload["jobs"]] == ["901", "902"]
        assert "shard 6 boom" in payload["output"]
        assert "shard 7 boom" in payload["output"]

    def test_resolves_run_from_workflow_and_head_sha(self, _resolver_ok, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda repo, workflow, *, branch, head_sha, token: {
                "id": 456,
                "status": "completed",
            },
        )
        _stub_collect(monkeypatch, [_failed_job("test", "boom")])

        outcome = handle_failed_log(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "workflow": "ci.yml",
                    "head_sha": "abc123",
                    "project": "yoke",
                }
            )
        )

        assert outcome.primary_success is True
        assert outcome.result_payload["run_id"] == "456"
        assert "boom" in outcome.result_payload["output"]

    def test_tail_lines_bounds_each_job_separately(self, _resolver_ok, monkeypatch):
        _stub_collect(
            monkeypatch,
            [
                _failed_job("a", "\n".join(f"a line {i}" for i in range(100)), "901"),
                _failed_job("b", "\n".join(f"b line {i}" for i in range(100)), "902"),
            ],
        )

        outcome = handle_failed_log(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "run_id": "1",
                    "tail_lines": 10,
                    "project": "yoke",
                }
            )
        )

        assert outcome.primary_success is True
        payload = outcome.result_payload
        assert payload["truncated"] is True
        assert "a line 99" in payload["output"]
        assert "b line 99" in payload["output"]
        assert [job["shown_line_count"] for job in payload["jobs"]] == [10, 10]

    def test_run_without_failed_jobs_reports_rather_than_errors(
        self, _resolver_ok, monkeypatch
    ):
        _stub_collect(monkeypatch, [])

        outcome = handle_failed_log(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["failed_job_count"] == 0
        assert "No failed jobs in run 123" in outcome.result_payload["output"]

    def test_missing_selector_fails_validation(self, _resolver_ok):
        outcome = handle_failed_log(
            _make_request({"repo": "upyoke/yoke", "project": "yoke"})
        )

        assert outcome.primary_success is False
        assert outcome.error is not None

    def test_registration_present(self):
        from yoke_core.domain.handlers import github_actions_failed_log as mod

        ids = [row["function_id"] for row in mod.REGISTRATIONS]
        assert "github_actions.failed_log" in ids
