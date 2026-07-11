"""Origin-owned GitHub App key custody during core deployment."""

from __future__ import annotations

import os
from types import SimpleNamespace
import subprocess

import pytest

from runtime.api.domain.test_deploy_core_container import (
    _HappyRemoteRunner,
    _env,
    patch_executor_boundaries,
)
from runtime.api.domain.test_deploy_remote import FakeRunner
from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_core_container import exec_core_container_deploy
from yoke_core.domain.deploy_core_container_remote import RemoteConvergenceError
from yoke_core.domain.deploy_remote import CommandResult
from yoke_core.domain.github_app_origin_key import (
    verification_and_promotion_command,
    verify_and_promote_in_core_image,
)

_APP_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:123:"
    "secret:yoke/prod/github-app-private-key-AbCdEf"
)


def _app_environment():
    return _env(github_app=github_app_deployment.GitHubAppDeploymentConfig(
        issuer="123456",
        api_url="https://api.github.com",
        private_key_secret_arn=_APP_SECRET_ARN,
    ))


def test_deploy_fetches_and_verifies_key_only_on_origin(monkeypatch):
    env = _app_environment()
    patch_executor_boundaries(monkeypatch, env)
    runner = _HappyRemoteRunner()

    rc = exec_core_container_deploy(
        "yoke",
        "prod",
        repo_path="/repo",
        runner=runner,
        emit=lambda _line: None,
    )

    assert rc == 0
    remote_commands = [
        call["argv"][-1]
        for call in runner.calls
        if call["argv"][0] == "ssh"
    ]
    fetch_index = next(
        index for index, command in enumerate(remote_commands)
        if "aws secretsmanager get-secret-value" in command
    )
    pull_index = next(
        index for index, command in enumerate(remote_commands)
        if "docker compose pull" in command
    )
    verify_index = next(
        index for index, command in enumerate(remote_commands)
        if "yoke_core.tools.github_app_identity_probe" in command
    )
    assert fetch_index < verify_index < pull_index
    assert _APP_SECRET_ARN in remote_commands[fetch_index]
    app_key_calls = [
        call for call in runner.calls
        if "aws secretsmanager get-secret-value" in call["argv"][-1]
        or "yoke_core.tools.github_app_identity_probe" in call["argv"][-1]
    ]
    assert all(call.get("input_text") is None for call in app_key_calls)
    assert "--query SecretString --output text >\"$tmp\"" in (
        remote_commands[fetch_index]
    )
    assert ".github-app-private-key.pem.pending" in remote_commands[fetch_index]
    assert "mv -f" in remote_commands[verify_index]


def test_origin_identity_failure_stops_deploy_without_key_output():
    runner = FakeRunner([
        CommandResult(1, "", "GitHub App identity verification failed\n")
    ])

    with pytest.raises(RemoteConvergenceError, match="verification failed"):
        verify_and_promote_in_core_image(
            runner, _app_environment(), "example/core:image"
        )

    call = runner.calls[0]
    assert call["input_text"] is None
    assert "github_app_identity_probe" in call["argv"][-1]
    assert _APP_SECRET_ARN not in call["argv"][-1]


def test_invalid_rotation_preserves_prior_key_bytes(tmp_path):
    compose_dir = tmp_path / "compose"
    compose_dir.mkdir()
    final = compose_dir / "github-app-private-key.pem"
    pending = compose_dir / ".github-app-private-key.pem.pending"
    final.write_bytes(b"prior-key-bytes")
    pending.write_bytes(b"invalid-new-key")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    docker.chmod(0o700)
    env = SimpleNamespace(
        compose_dir=str(compose_dir),
        github_app=SimpleNamespace(
            issuer="123456", api_url="https://api.github.com"
        ),
    )

    result = subprocess.run(
        ["sh", "-c", verification_and_promotion_command(env, "core:image")],
        env={"PATH": f"{fake_bin}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert final.read_bytes() == b"prior-key-bytes"
    assert not pending.exists()
