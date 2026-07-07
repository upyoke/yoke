"""Tests for the GitHub Actions self-hosted runner status handler."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pytest

from yoke_core.domain import github_actions_rest, github_variables_rest
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.handlers import github_actions_runners
from yoke_core.domain.handlers.github_actions_runners import (
    handle_runners_status,
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
        payload = {"repo": "upyoke/yoke"}
    return FunctionCallRequest(
        function="github_actions.runners.status",
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


@pytest.fixture(autouse=True)
def _runner_capability_absent(monkeypatch):
    monkeypatch.setattr(
        github_actions_runners,
        "cmd_capability_get_settings",
        lambda project, cap_type: None,
    )


def _runner(
    *,
    labels=("self-hosted", "Linux", "ARM64", "yoke-github-actions"),
    status="online",
    busy=False,
) -> Dict[str, Any]:
    return {
        "id": 7,
        "name": "yoke-github-actions-1",
        "status": status,
        "busy": busy,
        "labels": [{"name": label} for label in labels],
    }


class TestRunnersStatus:
    def test_no_registered_matching_runner_reports_register_action(self, monkeypatch):
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "register_runner"
        assert outcome.result_payload["ready"] is False
        assert outcome.result_payload["recommended_value"] == (
            '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        )

    def test_online_runner_without_variable_reports_set_variable(self, monkeypatch):
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": [_runner()]},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "set_variable"
        assert outcome.result_payload["matching_count"] == 1
        assert outcome.result_payload["online_matching_count"] == 1
        assert outcome.result_payload["idle_matching_count"] == 1
        assert outcome.result_payload["ready"] is False

    def test_online_runner_with_variable_reports_ready(self, monkeypatch):
        value = '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": [_runner(busy=True)]},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda *a, **kw: value,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "ready"
        assert outcome.result_payload["ready"] is True
        assert outcome.result_payload["idle_matching_count"] == 0
        assert outcome.result_payload["runners"][0]["labels"] == [
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ]

    def test_matching_offline_runner_reports_start_action(self, monkeypatch):
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": [_runner(status="offline")]},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda *a, **kw: (
                '["self-hosted","Linux","ARM64",'
                '"yoke-github-actions"]'
            ),
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "start_runner"
        assert outcome.result_payload["ready"] is False

    def test_label_matching_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": [_runner()]},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable",
            lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request({
            "repo": "upyoke/yoke",
            "required_labels": [
                "self-hosted", "linux", "arm64", "yoke-github-actions",
            ],
        }))

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "set_variable"
        assert outcome.result_payload["matching_count"] == 1

    def test_capability_settings_supply_route_when_repo_omitted(
        self, monkeypatch
    ):
        raw_settings = (
            '{"repo":"upyoke/yoke","runner_labels":["self-hosted",'
            '"Linux","X64","fast-ci"],"variable_name":"CUSTOM_RUNS_ON",'
            '"desired_runner_count":6,"max_runner_count":12,'
            '"instance":{"instance_type":"c7i.8xlarge",'
            '"architecture":"x64","root_volume_gb":800}}'
        )
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: raw_settings,
        )
        monkeypatch.setattr(
            github_actions_rest, "rest_get",
            lambda *a, **kw: {"runners": [_runner(labels=(
                "self-hosted", "Linux", "X64", "fast-ci",
            ))]},
        )

        def variable(repo, name, *, token):
            assert repo == "upyoke/yoke"
            assert name == "CUSTOM_RUNS_ON"
            return '["self-hosted","Linux","X64","fast-ci"]'

        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable", variable,
        )

        outcome = handle_runners_status(_make_request({"project": "yoke"}))

        assert outcome.primary_success is True
        assert outcome.result_payload["capability_configured"] is True
        assert outcome.result_payload["ready"] is True
        assert outcome.result_payload["required_labels"] == [
            "self-hosted", "Linux", "X64", "fast-ci",
        ]
        assert outcome.result_payload["desired_runner_count"] == 6
        assert outcome.result_payload["max_runner_count"] == 12
        assert outcome.result_payload["instance_type"] == "c7i.8xlarge"
        assert outcome.result_payload["root_volume_gb"] == 800

    def test_repo_required_when_no_capability_supplies_it(self):
        outcome = handle_runners_status(_make_request({"project": "yoke"}))

        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "repo must be owner/name" in outcome.error.message

    def test_transport_error_maps_to_typed_failure(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RestTransportError("GET /actions/runners exploded")

        monkeypatch.setattr(github_actions_rest, "rest_get", _boom)
        outcome = handle_runners_status(_make_request())
        assert outcome.primary_success is False
        assert outcome.error.code == "rest_transport_error"

    def test_registration_shape_is_read_only(self):
        entry = github_actions_runners.REGISTRATIONS[0]
        assert entry["function_id"] == "github_actions.runners.status"
        assert entry["side_effects"] == []
        assert entry["target_kinds"] == ["global"]
