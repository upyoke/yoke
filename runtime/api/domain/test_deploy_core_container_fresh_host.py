"""Fresh-host runtime convergence command-plan tests."""

from __future__ import annotations

import subprocess

import pytest

from yoke_core.domain.deploy_core_container_runtime_packages import (
    _AWS_CLI_INSTALL,
    _BASE_RUNTIME_INSTALL,
    _DOCKER_REPAIR,
    ensure_runtime_packages,
)
from yoke_core.domain.deploy_core_container_remote_errors import (
    RemoteConvergenceError,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.test_deploy_remote import FakeRunner


def _env() -> DeployEnvironment:
    return DeployEnvironment(
        project="yoke",
        deploy_namespace="yoke",
        env_name="prod",
        site_id="yoke-api",
        api_host="api.example.com",
        origin_host="origin.example.com",
        origin_port=80,
        ssh_user="ubuntu",
        ssh_key_path="/keys/origin-example.pem",
        aws_region="us-east-1",
        aws_account_id="123456789012",
        repository_name="yoke-core",
        api_port=8765,
        health_path="/v1/health",
        stack_name="yoke-prod",
        activation_state="active",
        state_backend="s3://yoke-pulumi-state?region=us-east-1",
        database_name="yoke_prod",
    )


def _remote_commands(runner: FakeRunner) -> list[str]:
    return [call["argv"][-1] for call in runner.calls]


@pytest.mark.parametrize(
    "command",
    (_BASE_RUNTIME_INSTALL, _DOCKER_REPAIR, _AWS_CLI_INSTALL),
)
def test_runtime_repair_commands_are_valid_posix_shell(command: str) -> None:
    parsed = subprocess.run(
        ["sh", "-n", "-c", command], capture_output=True, text=True, check=False
    )

    assert parsed.returncode == 0, parsed.stderr


def test_fresh_host_installs_aws_cli_v2_outside_apt() -> None:
    runner = FakeRunner(
        [
            CommandResult(1, "", "runtime missing"),
            CommandResult(0, "", ""),
            CommandResult(1, "", "docker missing"),
            CommandResult(0, "", ""),
            CommandResult(1, "", "aws missing"),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
        ]
    )

    ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    probe, base, docker_probe, docker_repair, aws_probe, aws_install, verify, enable = (
        _remote_commands(runner)
    )
    assert "command -v aws" in probe
    apt_packages = base.split("apt-get install -y -q ", 1)[1].split()
    assert "awscli" not in apt_packages
    for package in (
        "ca-certificates",
        "curl",
        "unzip",
        "amazon-ecr-credential-helper",
        "nginx",
    ):
        assert package in apt_packages
    assert "docker.io" not in apt_packages

    assert "docker compose version" in docker_probe
    assert "docker.io docker-compose-v2" in docker_repair
    assert "docker-compose-plugin" in docker_repair
    assert "existing Docker provider is not managed by apt" in docker_repair
    assert "command -v aws" in aws_probe
    assert "AWSCLI_ARCH=aarch64" in aws_install
    assert '"$(dpkg --print-architecture)" = "amd64"' in aws_install
    assert "AWSCLI_ARCH=x86_64" in aws_install
    assert (
        "https://awscli.amazonaws.com/awscli-exe-linux-${AWSCLI_ARCH}.zip"
        in aws_install
    )
    assert "unzip -q /tmp/awscliv2.zip -d /tmp" in aws_install
    assert "--install-dir /usr/local/aws-cli --update" in aws_install
    assert "--install-dir /usr/local/aws-cli; fi" in aws_install
    assert aws_install.count("rm -rf /tmp/aws /tmp/awscliv2.zip") == 2
    assert "command -v aws" in verify
    assert "systemctl enable --now docker nginx" in enable


def test_existing_docker_ce_is_adopted_when_only_aws_cli_is_missing() -> None:
    runner = FakeRunner(
        [
            CommandResult(1, "", "aws missing"),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
            CommandResult(1, "", "aws missing"),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
        ]
    )

    ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    commands = _remote_commands(runner)
    assert len(commands) == 7
    assert _DOCKER_REPAIR not in commands
    assert _AWS_CLI_INSTALL in commands
    assert all("docker.io docker-compose-v2" not in command for command in commands)


def test_runtime_install_failure_keeps_stdout_dependency_detail() -> None:
    runner = FakeRunner(
        [
            CommandResult(1, "", "runtime missing"),
            CommandResult(
                100,
                "containerd.io : Conflicts: containerd",
                "E: pkgProblemResolver generated breaks",
            ),
        ]
    )

    with pytest.raises(RemoteConvergenceError) as exc_info:
        ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    message = str(exc_info.value)
    assert "containerd.io : Conflicts: containerd" in message
    assert "pkgProblemResolver generated breaks" in message


def test_existing_host_skips_runtime_install() -> None:
    runner = FakeRunner([CommandResult(0, "", ""), CommandResult(0, "", "")])

    ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    commands = _remote_commands(runner)
    assert len(commands) == 2
    assert "command -v aws" in commands[0]
    assert all("apt-get" not in command for command in commands)
