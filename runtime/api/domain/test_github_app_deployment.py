"""Tests for environment-scoped GitHub App private-key delivery."""

from __future__ import annotations

import pytest

from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_core_container import render_service_files
from yoke_core.domain.deploy_remote import CommandResult

from runtime.api.domain.test_deploy_core_container import _BINDING, _env
from runtime.api.domain.test_deploy_remote import FakeRunner


_APP_CONFIG = github_app_deployment.GitHubAppDeploymentConfig(
    issuer="123456",
    api_url="https://api.github.com",
    private_key_secret_arn=(
        "arn:aws:secretsmanager:us-east-1:123:secret:yoke-github-app"
    ),
)


def test_github_app_config_rejects_env_line_injection():
    with pytest.raises(
        github_app_deployment.GitHubAppDeploymentConfigError,
        match="issuer must be",
    ):
        github_app_deployment.github_app_config_from_environment_settings(
            {
                "github_app": {
                    "issuer": "123\nYOKE_INJECTED=value",
                    "api_url": "https://api.github.com",
                    "private_key_secret_arn": (
                        "arn:aws:secretsmanager:us-east-1:123:secret:github"
                    ),
                }
            },
            env_hint="configure stage",
        )


def test_github_app_config_mounts_owner_only_key_reference():
    compose, _, env_file = render_service_files(
        _env(github_app=_APP_CONFIG), "img:tag", _BINDING
    )
    assert (
        "secrets:\n      - yoke-github-app-private-key"
    ) in compose
    assert "file: ./github-app-private-key.pem" in compose
    assert "YOKE_GITHUB_APP_ISSUER=123456" in env_file
    assert "YOKE_GITHUB_APP_API_URL=https://api.github.com" in env_file
    assert (
            "YOKE_GITHUB_APP_PRIVATE_KEY_FILE="
            "/run/secrets/yoke-github-app-private-key"
    ) in env_file
    assert _APP_CONFIG.private_key_secret_arn not in compose + env_file


def test_github_app_key_moves_only_through_ssh_stdin():
    runner = FakeRunner([CommandResult(0, "", "")])
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    github_app_deployment.converge_github_app_private_key(
        runner,
        _env(github_app=_APP_CONFIG),
        {"AWS_REGION": "us-east-1"},
        secret_loader=lambda *_args, **_kwargs: private_key,
    )
    call = runner.calls[0]
    assert private_key == call["input_text"]
    assert private_key not in " ".join(call["argv"])
    assert (
        "install -m 600 /dev/stdin "
        "/opt/yoke-core/github-app-private-key.pem"
    ) in call["argv"][-1]


def test_disabling_github_app_removes_stale_private_key():
    runner = FakeRunner([CommandResult(0, "", "")])
    github_app_deployment.converge_github_app_private_key(
        runner, _env(), {"AWS_REGION": "us-east-1"}
    )
    assert runner.calls[0]["argv"][-1] == (
        "rm -f /opt/yoke-core/github-app-private-key.pem"
    )
