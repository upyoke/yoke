"""Pulumi subprocess authority tests."""

import pytest

from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _authority_payload,
    _execute,
    _file_project,
)
from yoke_core.domain import deploy_remote
from yoke_core.tools.pulumi_exec import (
    PulumiExecError,
    _authority_env,
    aws_machine_capability_env,
)

_VARIABLES = "config:\n  yoke:github_access: variables\n"


def test_github_authority_uses_settings_project_and_both_token_names(tmp_path):
    seen = {}

    def auth_loader(project, **kwargs):
        seen["project"] = project
        seen["permissions"] = kwargs["required_permissions"]
        return type(
            "Auth", (), {"token": "token-value", "repo": "beebauman/externalwebapp"}
        )()

    def child_factory(command, **kwargs):
        seen["env"] = kwargs["env"]
        return _Child()

    _execute(
        _file_project(tmp_path, stack_text=_VARIABLES),
        ["preview"],
        github_auth_loader=auth_loader,
        child_factory=child_factory,
    )
    assert seen["project"] == "externalwebapp"
    assert seen["permissions"]["actions_variables"] == "write"
    assert seen["env"]["GITHUB_TOKEN"] == "token-value"
    assert seen["env"]["RUNNER_FLEET_GITHUB_TOKEN"] == "token-value"


def test_github_token_for_another_repository_refuses(tmp_path):
    with pytest.raises(PulumiExecError, match="does not match stack authority"):
        _execute(
            _file_project(tmp_path),
            ["preview"],
            github_auth_loader=lambda *a, **kw: type(
                "Auth", (), {"token": "t", "repo": "someone/else"}
            )(),
            child_factory=lambda *a, **kw: pytest.fail("child ran"),
        )


def test_registry_actions_uses_hosted_repository_token_broker(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    payload = _authority_payload("platform", "registry")
    payload["authority"].update(
        {
            "github_project": "platform",
            "github_repo": "upyoke/platform",
            "github_permissions": {
                "metadata": "read",
                "actions_variables": "write",
            },
            "hosted_repository_token_intent": "signed-broker-intent",
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
        return "hosted-registry-token"

    env, redaction = _authority_env(
        "platform",
        payload["authority"],
        payload,
        runner_fleet=False,
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
    payload = _authority_payload("platform", "registry")
    payload["authority"].update(
        {
            "github_project": "platform",
            "github_repo": "upyoke/platform",
            "github_permissions": {"actions_variables": "write"},
        }
    )
    with pytest.raises(PulumiExecError, match="provider-token broker"):
        _authority_env(
            "platform",
            payload["authority"],
            payload,
            runner_fleet=False,
            aws_env_loader=lambda *args, **kwargs: {},
            github_auth_loader=lambda *args, **kwargs: None,
        )


def test_local_bootstrap_refuses_non_runner_stack():
    payload = _authority_payload("yoke")
    payload["authority"]["github_repo"] = "upyoke/yoke"
    with pytest.raises(PulumiExecError, match="limited to the runner-fleet"):
        _authority_env(
            "yoke",
            payload["authority"],
            payload,
            runner_fleet=False,
            aws_env_loader=lambda *args, **kwargs: {},
            github_auth_loader=lambda *args, **kwargs: None,
            bootstrap_local_authority=True,
        )


def test_default_aws_authority_reads_machine_files_without_database(
    monkeypatch,
    tmp_path,
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

    _execute(
        _file_project(tmp_path),
        ["refresh", "--yes", "--non-interactive"],
        aws_env_loader=aws_machine_capability_env,
        child_factory=child_factory,
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

    _execute(
        _file_project(tmp_path),
        ["preview"],
        aws_env_loader=aws_machine_capability_env,
        child_factory=child_factory,
    )
    assert seen["env"]["AWS_ACCESS_KEY_ID"] == "ASIAOIDC"
    assert seen["env"]["AWS_SESSION_TOKEN"] == "oidc-session"


def test_aws_failure_is_redacted_and_actionable(tmp_path):
    with pytest.raises(PulumiExecError) as raised:
        _execute(
            _file_project(tmp_path),
            ["refresh"],
            aws_env_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("sensitive-value")
            ),
        )
    rendered = str(raised.value)
    assert "sensitive-value" not in rendered
    assert "machine_capability_unavailable" in rendered
    assert "capability secret set" in rendered


def test_github_failure_is_redacted_and_actionable(tmp_path):
    with pytest.raises(PulumiExecError) as raised:
        _execute(
            _file_project(tmp_path, stack_text=_VARIABLES),
            ["preview"],
            github_auth_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("ghu_sensitive-token")
            ),
        )
    rendered = str(raised.value)
    assert "ghu_sensitive-token" not in rendered
    assert "app_authority_unavailable" in rendered
    assert "github-binding status --project externalwebapp" in rendered


def test_github_failure_surfaces_loader_redacted_detail(tmp_path):
    class SafeAuthorityError(RuntimeError):
        pulumi_safe_message = (
            "project GitHub App binding lacks required permissions: repository_hooks"
        )

    with pytest.raises(PulumiExecError) as raised:
        _execute(
            _file_project(tmp_path),
            ["preview"],
            github_auth_loader=lambda *args, **kwargs: (_ for _ in ()).throw(
                SafeAuthorityError("redacted authority detail")
            ),
        )
    rendered = str(raised.value)
    assert "repository_hooks" in rendered
    assert "redacted authority detail" not in rendered
