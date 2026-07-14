"""CAS persistence and validation for runner-fleet capability settings."""

import json

import pytest

from yoke_core.domain import projects_capabilities_settings as pcs
from runtime.api.domain.test_projects_capabilities_settings import cap_db


_FIXTURES = (cap_db,)


class TestRunnerFleetCapabilitySettings:
    def test_settings_are_canonicalized(self, cap_db: str) -> None:
        pcs.cmd_capability_set_settings(
            "yoke", "github-actions-runner-fleet",
            '{"repo":"upyoke/yoke",'
            '"github_app":{"issuer":" Iv1.runner-fleet ",'
            '"api_url":"https://api.github.com/",'
            '"private_key_secret_arn":"arn:aws:secretsmanager:us-east-1:'
            '123456789012:secret:yoke-github-app-AbCdEf"},'
            '"network":{"deployment_ssh_environments":'
            '[" prod ","stage","prod"]},'
            '"desired_runner_count":1,'
            '"max_runner_count":1}',
            create=True, db_path=cap_db,
        )

        stored = json.loads(pcs.cmd_capability_get_settings(
            "yoke", "github-actions-runner-fleet", db_path=cap_db,
        ))
        assert stored["repo"] == "upyoke/yoke"
        assert stored["github_app"] == {
            "issuer": "Iv1.runner-fleet",
            "api_url": "https://api.github.com",
            "private_key_secret_arn": (
                "arn:aws:secretsmanager:us-east-1:123456789012:"
                "secret:yoke-github-app-AbCdEf"
            ),
        }
        assert stored["runner_labels"] == [
            "self-hosted", "Linux", "ARM64", "yoke-github-actions",
        ]
        assert stored["variable_name"] == "YOKE_LINUX_RUNS_ON"
        assert stored["routing_enabled"] is False
        assert "github_capability" not in stored
        assert stored["desired_runner_count"] == 1
        assert stored["max_runner_count"] == 1
        assert stored["lifecycle"]["ephemeral_runners"] is True
        assert stored["network"]["deployment_ssh_environments"] == [
            "prod", "stage",
        ]

    def test_rejects_shared_host_parallelism(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="one isolated runner host"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"desired_runner_count":2,"max_runner_count":4}',
                create=True, db_path=cap_db,
            )

    def test_rejects_zero_idle_grace(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"lifecycle":{"idle_shutdown_minutes":0}}',
                create=True, db_path=cap_db,
            )

    def test_rejects_repo_without_owner(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="owner/name"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"repo":"no-slash"}', create=True, db_path=cap_db,
            )

    @pytest.mark.parametrize("variable_name", ["9_ROUTE", "BAD-NAME", "GITHUB_ROUTE"])
    def test_rejects_invalid_variable_name(
        self, cap_db: str, variable_name: str,
    ) -> None:
        with pytest.raises(ValueError, match="variable_name"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                json.dumps({"variable_name": variable_name}),
                create=True, db_path=cap_db,
            )

    def test_rejects_incomplete_app_authority(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="private_key_secret_arn"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"github_app":{"issuer":"Iv1.runner-fleet",'
                '"api_url":"https://api.github.com"}}',
                create=True, db_path=cap_db,
            )

    def test_rejects_unknown_settings(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="extra_forbidden"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"unknown_selector":"unexpected"}',
                create=True, db_path=cap_db,
            )

    def test_rejects_empty_deployment_ssh_environment(
        self, cap_db: str,
    ) -> None:
        with pytest.raises(ValueError, match="non-empty environment names"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"network":{"deployment_ssh_environments":["prod"," "]}}',
                create=True, db_path=cap_db,
            )

    def test_rejects_empty_github_capability(self, cap_db: str) -> None:
        with pytest.raises(ValueError, match="non-empty when provided"):
            pcs.cmd_capability_set_settings(
                "yoke", "github-actions-runner-fleet",
                '{"github_capability":"  "}',
                create=True, db_path=cap_db,
            )
