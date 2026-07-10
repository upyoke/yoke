"""Tests for environment-scoped GitHub App private-key delivery."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_core_container import render_service_files
from yoke_core.domain.deploy_core_container_remote import RemoteConvergenceError
from yoke_core.domain.deploy_remote import CommandResult

from runtime.api.domain.test_deploy_core_container import _BINDING, _env
from runtime.api.domain.test_deploy_remote import FakeRunner
from runtime.api.domain.test_github_app_token_services import _private_key_pair


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
    assert ("secrets:\n      - yoke-github-app-private-key") in compose
    assert "file: ./github-app-private-key.pem" in compose
    assert "YOKE_GITHUB_APP_ISSUER=123456" in env_file
    assert "YOKE_GITHUB_APP_API_URL=https://api.github.com" in env_file
    assert (
        "YOKE_GITHUB_APP_PRIVATE_KEY_FILE=/run/secrets/yoke-github-app-private-key"
    ) in env_file
    assert _APP_CONFIG.private_key_secret_arn not in compose + env_file


def test_github_app_key_moves_only_through_ssh_stdin():
    runner = FakeRunner([CommandResult(0, "", "")])
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    verified = []
    prepared_key = github_app_deployment.preflight_github_app_private_key(
        runner,
        _env(github_app=_APP_CONFIG),
        {"AWS_REGION": "us-east-1"},
        secret_loader=lambda *_args, **_kwargs: private_key,
        identity_verifier=lambda **kwargs: verified.append(kwargs),
    )
    github_app_deployment.converge_github_app_private_key(
        runner,
        _env(github_app=_APP_CONFIG),
        private_key_pem=prepared_key,
    )
    assert len(verified) == 1
    assert verified[0]["runner"] is runner
    assert verified[0]["issuer"] == "123456"
    assert verified[0]["private_key_pem"] == private_key
    assert verified[0]["api_url"] == "https://api.github.com"
    call = runner.calls[0]
    assert private_key == call["input_text"]
    assert private_key not in " ".join(call["argv"])
    assert "os.replace" in call["argv"][-1]
    assert call["argv"][-1].endswith(" /opt/yoke-core/github-app-private-key.pem 600")


def test_identity_verifier_uses_origin_host_for_private_api():
    private_key, _public_key = _private_key_pair()
    response = '{"id":123456,"client_id":"Iv1.client","slug":"yoke"}'
    runner = FakeRunner([CommandResult(0, response, "")])

    identity = github_app_deployment.verify_github_app_identity(
        runner=runner,
        env=_env(),
        issuer="Iv1.client",
        private_key_pem=private_key.decode("utf-8"),
        api_url="https://github.internal.example/api/v3",
    )

    assert identity.app_id == 123456
    assert identity.client_id == "Iv1.client"
    assert identity.slug == "yoke"
    call = runner.calls[0]
    assert call["argv"][0] == "ssh"
    assert call["argv"][-1].endswith(
        " https://github.internal.example/api/v3/app"
    )
    jwt = call["input_text"]
    assert jwt.startswith("ey")
    assert jwt not in " ".join(call["argv"])
    assert jwt not in response


def test_identity_verifier_rejects_response_for_another_issuer():
    private_key, _public_key = _private_key_pair()
    runner = FakeRunner([CommandResult(
        0,
        '{"id":999,"client_id":"Iv1.other","slug":"other"}',
        "",
    )])
    with pytest.raises(
        github_app_deployment.GitHubAppIdentityVerificationError,
        match="does not match",
    ):
        github_app_deployment.verify_github_app_identity(
            runner=runner,
            env=_env(),
            issuer="123456",
            private_key_pem=private_key.decode("utf-8"),
            api_url="https://api.github.com",
        )


def test_identity_verifier_rejects_key_github_does_not_accept():
    private_key, _public_key = _private_key_pair()
    runner = FakeRunner([CommandResult(
        65, "", "github_app_identity_request_failed\n",
    )])

    with pytest.raises(
        github_app_deployment.GitHubAppIdentityVerificationError,
        match="request failed from the deployment origin",
    ):
        github_app_deployment.verify_github_app_identity(
            runner=runner,
            env=_env(),
            issuer="123456",
            private_key_pem=private_key.decode("utf-8"),
            api_url="https://api.github.com",
        )


def test_identity_verifier_rejects_redirect_without_exposing_jwt():
    private_key, _public_key = _private_key_pair()
    runner = FakeRunner([CommandResult(
        65, "", "github_app_identity_request_failed\n",
    )])

    with pytest.raises(
        github_app_deployment.GitHubAppIdentityVerificationError,
        match="request failed from the deployment origin",
    ):
        github_app_deployment.verify_github_app_identity(
            runner=runner,
            env=_env(),
            issuer="123456",
            private_key_pem=private_key.decode("utf-8"),
            api_url="https://api.github.com",
        )

    call = runner.calls[0]
    assert "HTTPRedirectHandler" in call["argv"][-1]
    assert "return None" in call["argv"][-1]
    assert call["input_text"] not in " ".join(call["argv"])
    assert call["input_text"] not in call["argv"][-1]


def test_failed_identity_verification_never_prepares_private_key():
    with pytest.raises(RemoteConvergenceError, match="verification failed"):
        github_app_deployment.preflight_github_app_private_key(
            FakeRunner(),
            _env(github_app=_APP_CONFIG),
            {"AWS_REGION": "us-east-1"},
            secret_loader=lambda *_args, **_kwargs: "private-key",
            identity_verifier=lambda **_kwargs: (_ for _ in ()).throw(
                ValueError("unsafe details")
            ),
        )


def test_disabling_github_app_removes_key_and_stranded_writer_temp(tmp_path):
    target = tmp_path / "github-app-private-key.pem"
    target.write_text("old-key\n", encoding="utf-8")
    orphan = tmp_path / ".github-app-private-key.pem.crashed.tmp"
    orphan.write_text("stranded-key\n", encoding="utf-8")
    orphan.chmod(0o600)
    env = SimpleNamespace(
        github_app=None,
        compose_dir=str(tmp_path),
        ssh_key_path="/keys/origin-example.pem",
        ssh_target="ubuntu@origin.example.com",
    )
    runner = FakeRunner([CommandResult(0, "", "")])
    github_app_deployment.converge_github_app_private_key(
        runner, env, private_key_pem=None,
    )
    command = runner.calls[0]["argv"][-1]
    assert " remove " in command
    assert command.endswith(f" {target}")

    subprocess.run(["sh", "-c", command], check=True)

    assert not target.exists()
    assert not orphan.exists()
