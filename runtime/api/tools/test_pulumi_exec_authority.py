"""Pulumi subprocess authority tests."""

from io import StringIO

import pytest

from runtime.api.tools.test_pulumi_exec_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)
from yoke_core.domain import deploy_remote
from yoke_core.tools.pulumi_exec import (
    PulumiExecError,
    _authority_env,
    execute_pulumi_command,
)


def test_github_authority_uses_bound_project_and_both_token_names(tmp_path):
    payload = _stack_payload()
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
        "github_permissions": {
            "metadata": "read",
            "actions_variables": "write",
        },
    })
    seen = {}

    def auth_loader(project, **kwargs):
        seen["project"] = project
        seen["permissions"] = kwargs["required_permissions"]
        return type("Auth", (), {
            "token": "token-value",
            "repo": "upyoke/platform",
        })()

    def child_factory(command, **kwargs):
        seen["env"] = kwargs["env"]
        return _Child()

    execute_pulumi_command(
        "yoke", "yoke-infra", ["preview"],
        config_loader=lambda project, stack: payload,
        project_root=_install_pulumi_project_files(tmp_path),
        aws_env_loader=lambda *args, **kwargs: {},
        github_auth_loader=auth_loader,
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert seen["project"] == "platform"
    assert seen["permissions"]["actions_variables"] == "write"
    assert seen["env"]["GITHUB_TOKEN"] == "token-value"
    assert seen["env"]["RUNNER_FLEET_GITHUB_TOKEN"] == "token-value"


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
        "runner_fleet_token_broker_function": "yoke-token-broker",
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
    }
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
    })
    seen = {}

    def local_loader(values, **kwargs):
        seen["values"] = values
        seen["kwargs"] = kwargs
        return type("Auth", (), {
            "token": "local-token",
            "repo": "upyoke/platform",
            "redaction_terms": ("local-token", "private-key-line"),
        })()

    env, redaction = _authority_env(
        "platform", payload["authority"], payload,
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
        "runner_fleet_token_broker_function": "yoke-token-broker",
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
    }
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
    })
    seen = {}

    def hosted_loader(project, authority_intent, aws_env):
        seen.update({
            "project": project,
            "authority_intent": authority_intent,
            "aws_env": dict(aws_env),
        })
        return "hosted-token"

    env, redaction = _authority_env(
        "platform", payload["authority"], payload,
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


def test_registry_actions_uses_hosted_repository_token_broker(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    payload = _stack_payload("platform", "yoke-registry")
    payload["stack_kind"] = "registry"
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
        "github_permissions": {
            "metadata": "read",
            "actions_variables": "write",
        },
        "hosted_repository_token_intent": "signed-broker-intent",
    })
    seen = {}

    def hosted_loader(project, authority_intent, aws_env):
        seen.update({
            "project": project,
            "authority_intent": authority_intent,
            "aws_env": dict(aws_env),
        })
        return "hosted-registry-token"

    env, redaction = _authority_env(
        "platform", payload["authority"], payload,
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "oidc-key",
        },
        github_auth_loader=lambda *args, **kwargs: pytest.fail(
            "consulted the ambient repository-token path"
        ),
        hosted_repository_token_loader=hosted_loader,
    )

    assert seen == {
        "project": "platform",
        "authority_intent": "signed-broker-intent",
        "aws_env": {"AWS_ACCESS_KEY_ID": "oidc-key"},
    }
    assert env["GITHUB_TOKEN"] == "hosted-registry-token"
    assert "hosted-registry-token" in redaction


def test_registry_actions_requires_configured_repository_broker(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    payload = _stack_payload("platform", "yoke-registry")
    payload["stack_kind"] = "registry"
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
        "github_permissions": {"actions_variables": "write"},
    })
    with pytest.raises(PulumiExecError, match="provider-token broker"):
        _authority_env(
            "platform", payload["authority"], payload,
            aws_env_loader=lambda *args, **kwargs: {},
            github_auth_loader=lambda *args, **kwargs: None,
        )

def test_local_bootstrap_refuses_non_runner_stack():
    payload = _stack_payload()
    payload["authority"]["github_repo"] = "upyoke/yoke"
    with pytest.raises(PulumiExecError, match="limited to the runner-fleet"):
        _authority_env(
            "yoke", payload["authority"], payload,
            aws_env_loader=lambda *args, **kwargs: {},
            github_auth_loader=lambda *args, **kwargs: None,
            bootstrap_local_authority=True,
        )


def test_default_aws_authority_reads_machine_files_without_database(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(
        deploy_remote.capability_machine_secrets,
        "read_machine_capability_secret",
        lambda project, capability, key: {
            "access_key_id": "AKIAMACHINE",
            "secret_access_key": "machine-secret",
            "session_token": None,
        }[key],
    )
    monkeypatch.setattr(
        deploy_remote,
        "cmd_capability_get_secret",
        lambda *args: pytest.fail("consulted connected database authority"),
    )
    seen = {}

    def child_factory(command, **kwargs):
        seen["env"] = kwargs["env"]
        return _Child()

    execute_pulumi_command(
        "yoke", "yoke-infra", ["refresh", "--yes", "--non-interactive"],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=_install_pulumi_project_files(tmp_path),
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert seen["env"]["AWS_ACCESS_KEY_ID"] == "AKIAMACHINE"


def test_default_aws_authority_preserves_actions_oidc(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ASIAOIDC")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "oidc-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "oidc-session")
    monkeypatch.setattr(
        deploy_remote.capability_machine_secrets,
        "read_machine_capability_secret",
        lambda *args: pytest.fail("read machine files in GitHub Actions"),
    )
    seen = {}

    def child_factory(command, **kwargs):
        seen["env"] = kwargs["env"]
        return _Child()

    execute_pulumi_command(
        "yoke", "yoke-infra", ["preview"],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=_install_pulumi_project_files(tmp_path),
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert seen["env"]["AWS_ACCESS_KEY_ID"] == "ASIAOIDC"
    assert seen["env"]["AWS_SESSION_TOKEN"] == "oidc-session"


def test_aws_failure_is_redacted_and_actionable(tmp_path):
    with pytest.raises(PulumiExecError) as raised:
        execute_pulumi_command(
            "platform", "yoke-stage", ["refresh"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=_install_pulumi_project_files(tmp_path),
            aws_env_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("sensitive-value")
            ),
        )
    rendered = str(raised.value)
    assert "sensitive-value" not in rendered
    assert "machine_capability_unavailable" in rendered
    assert "capability secret set" in rendered


def test_github_failure_is_redacted_and_actionable(tmp_path):
    payload = _stack_payload()
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
        "github_permissions": {"actions_variables": "write"},
    })
    with pytest.raises(PulumiExecError) as raised:
        execute_pulumi_command(
            "yoke", "yoke-infra", ["preview"],
            config_loader=lambda project, stack: payload,
            project_root=_install_pulumi_project_files(tmp_path),
            aws_env_loader=lambda *args, **kwargs: {},
            github_auth_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("ghu_sensitive-token")
            ),
        )
    rendered = str(raised.value)
    assert "ghu_sensitive-token" not in rendered
    assert "app_authority_unavailable" in rendered
    assert "github-binding status" in rendered
