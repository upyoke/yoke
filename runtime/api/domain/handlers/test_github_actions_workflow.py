"""Tests for hosted GitHub Actions workflow dispatch and run queries."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.handlers import github_actions_workflow
from yoke_core.domain.handlers.github_actions_workflow import (
    handle_run_jobs_count,
    handle_workflow_find_run,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


_RESOLVED = ProjectGithubAuth(
    project="platform",
    repo="upyoke/platform",
    token="ghs_test_token",
)


def _make_request(
    function: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    target_kind: str = "global",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="test-session"),
        target=TargetRef(kind=target_kind),
        payload=dict(payload or {}),
    )


def _find_request(
    payload: Optional[Dict[str, Any]] = None,
) -> FunctionCallRequest:
    return _make_request(
        "github_actions.workflow.find_run",
        payload
        or {
            "project": "platform",
            "repo": "upyoke/platform",
            "workflow": "yoke-env-deploy.yml",
            "head_sha": "abc123",
        },
    )


def _jobs_request(
    payload: Optional[Dict[str, Any]] = None,
) -> FunctionCallRequest:
    return _make_request(
        "github_actions.run.jobs_count",
        payload
        or {
            "project": "platform",
            "repo": "upyoke/platform",
            "run_id": "98765",
            "attempt": 2,
        },
    )


@pytest.fixture
def _resolved_auth(monkeypatch):
    calls = []

    def _resolve(project, **kwargs):
        calls.append((project, kwargs))
        return _RESOLVED

    monkeypatch.setattr(
        "yoke_core.domain.project_github_auth.resolve_project_github_auth",
        _resolve,
    )
    return calls


class TestWorkflowFindRun:
    def test_queries_with_read_permission_and_excludes_run(
        self, monkeypatch, _resolved_auth,
    ):
        calls = []

        def _get(path, *, query, token):
            calls.append((path, query, token))
            return {
                "workflow_runs": [
                    {"id": 11, "status": "completed"},
                    {
                        "id": 12,
                        "status": "in_progress",
                        "conclusion": None,
                        "html_url": "https://github.test/actions/runs/12",
                    },
                ]
            }

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", _get,
        )
        request = _find_request({
            "project": "platform",
            "repo": "upyoke/platform",
            "workflow": "yoke-env-deploy.yml",
            "branch": "stage",
            "event": "workflow_dispatch",
            "exclude_run_id": "11",
        })

        outcome = handle_workflow_find_run(request)

        assert outcome.primary_success is True
        assert outcome.result_payload == {
            "found": True,
            "run_id": "12",
            "status": "in_progress",
            "conclusion": None,
            "html_url": "https://github.test/actions/runs/12",
        }
        assert calls == [
            (
                "/repos/upyoke/platform/actions/workflows/"
                "yoke-env-deploy.yml/runs",
                {
                    "per_page": "10",
                    "branch": "stage",
                    "event": "workflow_dispatch",
                },
                "ghs_test_token",
            )
        ]
        assert _resolved_auth == [
            (
                "platform",
                {"required_permissions": GITHUB_ACTIONS_READ_PERMISSION_LEVELS},
            )
        ]

    @pytest.mark.parametrize(
        "response",
        [None, [], {}, {"workflow_runs": {}}, {"workflow_runs": [None]}],
    )
    def test_malformed_run_lookup_fails_closed(
        self, monkeypatch, _resolved_auth, response,
    ):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: response,
        )

        outcome = handle_workflow_find_run(_find_request())

        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"

    def test_valid_empty_run_list_is_not_found(
        self, monkeypatch, _resolved_auth,
    ):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: {"workflow_runs": []},
        )

        outcome = handle_workflow_find_run(_find_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["found"] is False
        assert outcome.result_payload["run_id"] is None


class TestRunJobsCount:
    def test_counts_jobs_with_read_permission(
        self, monkeypatch, _resolved_auth,
    ):
        calls = []

        def _get(path, *, token):
            calls.append((path, token))
            return {"total_count": 4, "jobs": []}

        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get", _get,
        )

        outcome = handle_run_jobs_count(_jobs_request())

        assert outcome.primary_success is True
        assert outcome.result_payload == {"run_id": "98765", "count": 4}
        assert calls == [
            (
                "/repos/upyoke/platform/actions/runs/98765/attempts/2/jobs",
                "ghs_test_token",
            )
        ]
        assert _resolved_auth == [
            (
                "platform",
                {"required_permissions": GITHUB_ACTIONS_READ_PERMISSION_LEVELS},
            )
        ]

    @pytest.mark.parametrize(
        "response",
        [
            None,
            [],
            {},
            {"total_count": None},
            {"total_count": True},
            {"total_count": -1},
            {"total_count": "not-an-integer"},
        ],
    )
    def test_malformed_jobs_response_fails_closed(
        self, monkeypatch, _resolved_auth, response,
    ):
        monkeypatch.setattr(
            "yoke_core.domain.github_actions_rest.rest_get",
            lambda *args, **kwargs: response,
        )

        outcome = handle_run_jobs_count(_jobs_request())

        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"


class TestRegistration:
    def test_dispatch_is_session_free_but_still_guarded(self):
        dispatch = next(
            entry
            for entry in github_actions_workflow.REGISTRATIONS
            if entry["function_id"] == "github_actions.workflow.dispatch"
        )

        assert dispatch["ambient_session_required"] is False
        assert dispatch["target_kinds"] == ["global"]
        assert dispatch["claim_required_kind"] is None
        assert dispatch["side_effects"] == ["github_actions_workflow_dispatch"]
        assert "project_auth_required" in dispatch["guardrails"]
        assert "api_token_actor_bound" in dispatch["guardrails"]
        assert "handler_managed_idempotency" in dispatch["guardrails"]

    def test_all_workflow_operations_are_registered(self):
        assert {
            entry["function_id"]
            for entry in github_actions_workflow.REGISTRATIONS
        } == {
            "github_actions.workflow.dispatch",
            "github_actions.workflow.dispatch_once",
            "github_actions.workflow.find_run",
            "github_actions.run.jobs_count",
        }
