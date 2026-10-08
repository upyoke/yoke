"""Runner-fleet subprocess intent and repository-token authority."""

import pytest

from runtime.api.tools.test_pulumi_exec_support import _stack_payload
from yoke_core.tools import pulumi_exec_authority
from yoke_core.tools.pulumi_exec import _authority_env


def test_runner_fleet_local_bootstrap_uses_scoped_render_values():
    payload = _stack_payload("platform", "yoke-runner-fleet")
    payload["stack_kind"] = "runner-fleet"
    payload["render_values"] = {
        "deploy_namespace": "yoke",
        "runner_fleet_architecture": "arm64",
        "runner_fleet_deployment_ssh_stack_outputs_json": "{}",
        "runner_fleet_github_api_url": "https://api.github.com",
        "runner_fleet_github_app_issuer": "42",
        "runner_fleet_github_capability": "github-runner",
        "runner_fleet_github_installation_id": "7",
        "runner_fleet_repo": "upyoke/platform",
        "runner_fleet_github_private_key_secret_arn": "secret-arn",
        "runner_fleet_github_repo_name": "platform",
        "runner_fleet_github_repo_owner": "upyoke",
        "runner_fleet_github_repository_id": "99",
        "runner_fleet_github_web_url": "https://github.com",
        "runner_fleet_idle_shutdown_minutes": "30",
        "runner_fleet_instance_type": "m7g.2xlarge",
        "runner_fleet_labels_json": '["self-hosted","Linux","ARM64"]',
        "runner_fleet_max_runner_count": "4",
        "runner_fleet_root_volume_gb": "200",
        "runner_fleet_routing_enabled": "true",
        "runner_fleet_runner_count": "4",
        "runner_fleet_shutdown_mode": "terminate",
        "runner_fleet_lifecycle_writers_paused": "false",
        "runner_fleet_lifecycle_code_frozen": "false",
        "runner_fleet_token_broker_function": "yoke-token-broker",
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
    }
    payload["authority"].update(
        {
            "github_project": "platform",
            "github_repo": "upyoke/platform",
        }
    )
    seen = {}

    def local_loader(values, **kwargs):
        seen["values"] = values
        seen["kwargs"] = kwargs
        return type(
            "Auth",
            (),
            {
                "token": "local-token",
                "repo": "upyoke/platform",
                "redaction_terms": ("local-token", "private-key-line"),
            },
        )()

    env, redaction = _authority_env(
        "platform",
        payload["authority"],
        payload,
        aws_env_loader=lambda *args, **kwargs: {"AWS_ACCESS_KEY_ID": "key"},
        github_auth_loader=lambda *args, **kwargs: pytest.fail(
            "consulted the user-token path"
        ),
        bootstrap_local_authority=True,
        local_github_auth_loader=local_loader,
    )

    assert seen["values"]["runner_fleet_repo"] == "upyoke/platform"
    assert seen["kwargs"]["region"] == "us-east-1"
    assert env["GITHUB_TOKEN"] == "local-token"
    assert env["YOKE_RUNNER_FLEET_AUTHORITY_INTENT"]
    assert "private-key-line" in redaction


def test_runner_fleet_normal_local_authority_sets_intent(monkeypatch):
    payload = _stack_payload("platform", "yoke-runner-fleet")
    payload["stack_kind"] = "runner-fleet"
    payload["render_values"] = {
        "deploy_namespace": "yoke",
        "runner_fleet_repo": "upyoke/platform",
    }
    payload["authority"].update(
        {
            "github_project": "platform",
            "github_repo": "upyoke/platform",
        }
    )
    seen = {}
    monkeypatch.setattr(
        pulumi_exec_authority,
        "authority_intent_envelope_from_values",
        lambda **kwargs: seen.setdefault("intent_kwargs", kwargs) and "intent",
    )

    env, _ = pulumi_exec_authority.authority_env(
        "platform",
        payload["authority"],
        payload,
        aws_env_loader=lambda *args, **kwargs: {},
        github_auth_loader=lambda *args, **kwargs: type(
            "Auth",
            (),
            {
                "token": "user-token",
                "repo": "upyoke/platform",
            },
        )(),
    )

    assert env["YOKE_RUNNER_FLEET_AUTHORITY_INTENT"] == "intent"
    assert seen["intent_kwargs"]["values"]["runner_fleet_repo"] == ("upyoke/platform")


def test_runner_fleet_actions_uses_hosted_repository_token_broker(
    monkeypatch,
):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    payload = _stack_payload("platform", "yoke-runner-fleet")
    payload["stack_kind"] = "runner-fleet"
    payload["render_values"] = {
        "deploy_namespace": "yoke",
        "runner_fleet_architecture": "arm64",
        "runner_fleet_deployment_ssh_stack_outputs_json": "{}",
        "runner_fleet_github_api_url": "https://api.github.com",
        "runner_fleet_github_app_issuer": "42",
        "runner_fleet_github_capability": "github-runner",
        "runner_fleet_github_installation_id": "7",
        "runner_fleet_repo": "upyoke/platform",
        "runner_fleet_github_private_key_secret_arn": "secret-arn",
        "runner_fleet_github_repo_name": "platform",
        "runner_fleet_github_repo_owner": "upyoke",
        "runner_fleet_github_repository_id": "99",
        "runner_fleet_github_web_url": "https://github.com",
        "runner_fleet_idle_shutdown_minutes": "30",
        "runner_fleet_instance_type": "m7g.2xlarge",
        "runner_fleet_labels_json": '["self-hosted","Linux","ARM64"]',
        "runner_fleet_max_runner_count": "4",
        "runner_fleet_root_volume_gb": "200",
        "runner_fleet_routing_enabled": "true",
        "runner_fleet_runner_count": "4",
        "runner_fleet_shutdown_mode": "terminate",
        "runner_fleet_lifecycle_writers_paused": "false",
        "runner_fleet_lifecycle_code_frozen": "false",
        "runner_fleet_token_broker_function": "yoke-token-broker",
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
    }
    payload["authority"].update(
        {
            "github_project": "platform",
            "github_repo": "upyoke/platform",
        }
    )
    seen = {}

    def hosted_loader(project, authority_intent, aws_env):
        seen.update(
            {
                "project": project,
                "authority_intent": authority_intent,
                "aws_env": dict(aws_env),
            }
        )
        return "hosted-token"

    env, redaction = _authority_env(
        "platform",
        payload["authority"],
        payload,
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "oidc-key",
        },
        github_auth_loader=lambda *args, **kwargs: pytest.fail(
            "consulted the ordinary repository-token path"
        ),
        hosted_repository_token_loader=hosted_loader,
    )

    assert seen["project"] == "platform"
    assert seen["authority_intent"]
    assert seen["aws_env"]["AWS_ACCESS_KEY_ID"] == "oidc-key"
    assert env["GITHUB_TOKEN"] == "hosted-token"
    assert env["YOKE_RUNNER_FLEET_AUTHORITY_INTENT"]
    assert "hosted-token" in redaction
