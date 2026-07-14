"""Routing-state coverage for the GitHub Actions runner status handler."""

import json

from yoke_core.domain import github_actions_rest, github_variables_rest
from yoke_core.domain.handlers import github_actions_runners
from yoke_core.domain.handlers.github_actions_runners import (
    handle_runners_status,
)
from runtime.api.domain.handlers.github_actions_runners_test_support import (
    _auth_resolved,
    _configure_runner_capability,
    _make_request,
    _runner,
    _runner_app,
    _runner_capability_absent,
)


# Imported autouse fixtures must remain module globals for pytest discovery.
_FIXTURES = (_auth_resolved, _runner_capability_absent)


class TestRunnersStatusRouting:
    def test_online_runner_with_variable_reports_ready(self, monkeypatch):
        _configure_runner_capability(monkeypatch)
        value = '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": [_runner(busy=True)]},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: value,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "ready"
        assert outcome.result_payload["routing_armed"] is True
        assert outcome.result_payload["ready"] is True
        assert outcome.result_payload["idle_matching_count"] == 0
        assert outcome.result_payload["runners"][0]["labels"] == [
            "self-hosted",
            "Linux",
            "ARM64",
            "yoke-github-actions",
        ]

    def test_matching_offline_runner_reports_start_action(self, monkeypatch):
        _configure_runner_capability(monkeypatch)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": [_runner(status="offline")]},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: '["self-hosted","Linux","ARM64","yoke-github-actions"]',
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "start_runner"
        assert outcome.result_payload["ready"] is False

    def test_label_matching_is_case_insensitive(self, monkeypatch):
        _configure_runner_capability(monkeypatch)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": [_runner()]},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: None,
        )

        outcome = handle_runners_status(
            _make_request(
                {
                    "repo": "upyoke/yoke",
                    "required_labels": [
                        "self-hosted",
                        "linux",
                        "arm64",
                        "yoke-github-actions",
                    ],
                }
            )
        )

        assert outcome.primary_success is True
        assert outcome.result_payload["action"] == "apply_runner_fleet"
        assert outcome.result_payload["matching_count"] == 1

    def test_existing_nonmatching_route_requires_pulumi_adoption(
        self,
        monkeypatch,
    ):
        _configure_runner_capability(monkeypatch)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: '["ubuntu-latest"]',
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["variable_exists"] is True
        assert outcome.result_payload["routing_armed"] is False
        assert outcome.result_payload["action"] == ("adopt_runner_routing_variable")
        assert "one-time pulumi import" in outcome.result_payload["message"]

    def test_capability_settings_supply_route_when_repo_omitted(
        self,
        monkeypatch,
    ):
        raw_settings = json.dumps({
            "repo": "upyoke/yoke",
            "github_capability": "github",
            "github_app": _runner_app(),
            "runner_labels": ["self-hosted", "Linux", "X64", "fast-ci"],
            "variable_name": "CUSTOM_RUNS_ON",
            "routing_enabled": True,
            "desired_runner_count": 1,
            "max_runner_count": 1,
            "instance": {
                "instance_type": "c7i.8xlarge",
                "architecture": "x64",
                "root_volume_gb": 800,
            },
        })
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: raw_settings,
        )
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {
                "runners": [
                    _runner(
                        labels=(
                            "self-hosted",
                            "Linux",
                            "X64",
                            "fast-ci",
                        )
                    )
                ]
            },
        )

        def variable(repo, name, *, token):
            assert repo == "upyoke/yoke"
            assert name == "CUSTOM_RUNS_ON"
            return '["self-hosted","Linux","X64","fast-ci"]'

        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            variable,
        )

        outcome = handle_runners_status(_make_request({"project": "yoke"}))

        assert outcome.primary_success is True
        assert outcome.result_payload["capability_configured"] is True
        assert outcome.result_payload["github_capability"] == "github"
        assert outcome.result_payload["ready"] is True
        assert outcome.result_payload["required_labels"] == [
            "self-hosted",
            "Linux",
            "X64",
            "fast-ci",
        ]
        assert outcome.result_payload["desired_runner_count"] == 1
        assert outcome.result_payload["max_runner_count"] == 1
        assert outcome.result_payload["instance_type"] == "c7i.8xlarge"
        assert outcome.result_payload["root_volume_gb"] == 800

    def test_autoscaled_fleet_reports_routing_armed_without_runners(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            github_actions_runners,
            "cmd_capability_get_settings",
            lambda project, cap_type: json.dumps({
                "repo": "upyoke/yoke",
                "github_capability": "github",
                "github_app": _runner_app(),
                "routing_enabled": True,
            }),
        )
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: '["ARM64", "self-hosted", "yoke-github-actions", "linux"]',
        )

        outcome = handle_runners_status(_make_request({"project": "yoke"}))

        assert outcome.primary_success is True
        assert outcome.result_payload["capability_configured"] is True
        assert outcome.result_payload["routing_armed"] is True
        assert outcome.result_payload["ready"] is False
        assert outcome.result_payload["action"] == "routing_armed_idle"
        assert "autoscaling is configured" in outcome.result_payload["message"]
        assert (
            "no matching runner is currently registered"
            in (outcome.result_payload["message"])
        )
        assert "healthy" not in outcome.result_payload["message"]
        assert "will start" not in outcome.result_payload["message"]

    def test_disabled_route_uses_hosted_fallback(self, monkeypatch):
        _configure_runner_capability(monkeypatch, routing_enabled=False)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: None,
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["routing_enabled"] is False
        assert outcome.result_payload["routing_armed"] is False
        assert outcome.result_payload["action"] == "routing_disabled"
        assert "hosted fallback" in outcome.result_payload["message"]

    def test_disabled_route_distinguishes_nonmatching_existing_variable(
        self,
        monkeypatch,
    ):
        _configure_runner_capability(monkeypatch, routing_enabled=False)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: '["ubuntu-latest"]',
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["variable_exists"] is True
        assert outcome.result_payload["routing_armed"] is False
        assert outcome.result_payload["action"] == ("resolve_runner_routing_variable")
        assert (
            "not a clean hosted-fallback state" in (outcome.result_payload["message"])
        )

    def test_disabled_route_with_self_hosted_drift_reports_apply(
        self,
        monkeypatch,
    ):
        _configure_runner_capability(monkeypatch, routing_enabled=False)
        monkeypatch.setattr(
            github_actions_rest,
            "rest_get",
            lambda *a, **kw: {"runners": []},
        )
        monkeypatch.setattr(
            github_variables_rest,
            "get_repo_variable",
            lambda *a, **kw: '["self-hosted","Linux","ARM64","yoke-github-actions"]',
        )

        outcome = handle_runners_status(_make_request())

        assert outcome.primary_success is True
        assert outcome.result_payload["routing_enabled"] is False
        assert outcome.result_payload["routing_armed"] is True
        assert outcome.result_payload["action"] == "apply_runner_fleet"
        assert "remove the managed variable" in outcome.result_payload["message"]
