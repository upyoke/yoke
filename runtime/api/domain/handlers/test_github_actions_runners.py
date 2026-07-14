"""Tests for the GitHub Actions self-hosted runner status handler."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
    GITHUB_VARIABLES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain import github_actions_rest, github_variables_rest
from yoke_core.domain import github_actions_runner_status_readiness
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.handlers import github_actions_runners
from yoke_core.domain.handlers.github_actions_runners import (
    handle_runners_status,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from runtime.api.domain.handlers.github_actions_runners_test_support import (
    _auth_resolved,
    _configure_runner_capability,
    _make_request,
    _renderer_settings,
    _runner,
    _runner_app,
    _runner_capability_absent,
)

# Imported autouse fixtures must remain module globals for pytest discovery.
_FIXTURES = (_auth_resolved, _runner_capability_absent)


class TestRunnersStatus:
    def test_rejects_missing_project(self):
        outcome = handle_runners_status(_make_request(include_project=False))
        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "project" in outcome.error.message

    def test_rejects_noncanonical_runner_capability(self):
        outcome = handle_runners_status(_make_request({
            "repo": "upyoke/yoke",
            "runner_capability": "custom-runner-fleet",
        }))

        assert outcome.primary_success is False
        assert outcome.error.code == "invalid_payload"
        assert "runner_capability" in outcome.error.message

    def test_missing_optional_administration_permission_skips_request(
        self, monkeypatch
    ):
        resolved = ProjectGithubAuth(
            project="yoke",
            repo="upyoke/yoke",
            token="github-user-token",
            permissions={"checks": "read"},
        )
        monkeypatch.setattr(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            lambda project, **kwargs: resolved,
        )
        called = False

        def unexpected_request(*args, **kwargs):
            nonlocal called
            called = True
            return {"runners": []}

        monkeypatch.setattr(github_actions_rest, "rest_get", unexpected_request)

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is False
        assert outcome.error.code == "github_app_permission_required"
        assert "Administration: Read" in outcome.error.message
        assert called is False

    def test_absent_capability_reports_configuration_action(
        self, monkeypatch, _auth_resolved,
    ):
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
        assert outcome.result_payload["action"] == "configure_runner_fleet"
        assert outcome.result_payload["github_capability"] is None
        assert outcome.result_payload["routing_enabled"] is False
        assert outcome.result_payload["routing_armed"] is False
        assert outcome.result_payload["ready"] is False
        assert outcome.result_payload["recommended_value"] == (
            '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        )
        assert _auth_resolved == [
            (
                "yoke",
                {
                    "required_permissions": {
                        **GITHUB_ADMINISTRATION_READ_PERMISSION_LEVELS,
                        **GITHUB_VARIABLES_READ_PERMISSION_LEVELS,
                    }
                },
            )
        ]

    def test_enabled_route_without_variable_reports_apply(self, monkeypatch):
        _configure_runner_capability(monkeypatch)
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
        assert outcome.result_payload["action"] == "apply_runner_fleet"
        assert "apply the runner-fleet Pulumi stack" in (
            outcome.result_payload["message"]
        )
        assert outcome.result_payload["routing_enabled"] is True
        assert outcome.result_payload["github_capability"] == "github"
        assert outcome.result_payload["matching_count"] == 1
        assert outcome.result_payload["online_matching_count"] == 1
        assert outcome.result_payload["idle_matching_count"] == 1
        assert outcome.result_payload["routing_armed"] is False
        assert outcome.result_payload["ready"] is False

    def test_configured_route_requires_explicit_github_selector(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: (
                '{"repo":"upyoke/yoke","routing_enabled":true}'
            ),
        )
        monkeypatch.setattr(
            github_actions_rest, "rest_get", lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable", lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["capability_configured"] is True
        assert outcome.result_payload["github_capability"] is None
        assert outcome.result_payload["action"] == "configure_runner_fleet"
        assert "github-actions-runner-fleet capability" in (
            outcome.result_payload["message"]
        )

    def test_configured_route_requires_explicit_app_authority(
        self, monkeypatch,
    ):
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: (
                '{"repo":"upyoke/yoke","github_capability":"github",'
                '"routing_enabled":true}'
            ),
        )
        monkeypatch.setattr(
            github_actions_rest, "rest_get", lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable", lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["github_capability"] == "github"
        assert outcome.result_payload["github_app_configured"] is False
        assert outcome.result_payload["action"] == "configure_runner_fleet"
        assert "github_app" in outcome.result_payload["message"]

    @pytest.mark.parametrize(
        ("renderer_settings", "expected_error"),
        [
            (
                _renderer_settings(runner_settings={
                    "repo": "upyoke/yoke",
                    "github_capability": "github",
                    "github_app": _runner_app(
                        api_url="https://github.example.com/api/v3",
                    ),
                    "routing_enabled": True,
                }),
                "API URL must match",
            ),
            (
                _renderer_settings(github_permissions={
                    "administration": "write",
                    "repository_hooks": "write",
                }),
                "Variables: write",
            ),
        ],
    )
    def test_renderer_preflight_blocks_guaranteed_apply_failure(
        self, monkeypatch, renderer_settings, expected_error,
    ):
        runner = renderer_settings.capabilities[
            "github-actions-runner-fleet"
        ]
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: json.dumps(runner),
        )
        monkeypatch.setattr(
            github_actions_runner_status_readiness,
            "load_project_renderer_settings",
            lambda project: renderer_settings,
        )
        monkeypatch.setattr(
            github_actions_rest, "rest_get", lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest, "get_repo_variable", lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["capability_configured"] is True
        assert outcome.result_payload["capability_render_ready"] is False
        assert expected_error in outcome.result_payload["configuration_error"]
        assert outcome.result_payload["action"] == "configure_runner_fleet"
        assert outcome.result_payload["ready"] is False

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
