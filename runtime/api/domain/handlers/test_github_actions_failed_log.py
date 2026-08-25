"""Tests for the ``github_actions.failed_log`` handler."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
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


class TestHandleFailedLog:
    def test_returns_log_tail_for_explicit_run(self, _resolver_ok, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_logs.fetch_failed_log",
            lambda repo, run_id, *, token: {"build": "line one\nline two"},
        )

        outcome = handle_failed_log(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload == {
            "run_id": "123",
            "output": "line one\nline two",
            "truncated": False,
        }

    def test_resolves_run_from_workflow_and_head_sha(self, _resolver_ok, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.latest_workflow_run",
            lambda repo, workflow, *, branch, head_sha, token: {
                "id": 456,
                "status": "completed",
            },
        )
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_logs.fetch_failed_log",
            lambda repo, run_id, *, token: {"test": "boom"},
        )

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
        assert outcome.result_payload["output"] == "boom"

    def test_truncates_to_tail_lines(self, _resolver_ok, monkeypatch):
        log_text = "\n".join(f"line {i}" for i in range(100))
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_logs.fetch_failed_log",
            lambda repo, run_id, *, token: {"build": log_text},
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
        assert outcome.result_payload["truncated"] is True
        assert "showing last 10 lines" in outcome.result_payload["output"]
        assert "line 99" in outcome.result_payload["output"]

    def test_empty_log_fails(self, _resolver_ok, monkeypatch):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_logs.fetch_failed_log",
            lambda repo, run_id, *, token: {},
        )

        outcome = handle_failed_log(_make_request())

        assert outcome.primary_success is False
        assert outcome.error is not None
        assert "no failed-step" in outcome.error.message

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
