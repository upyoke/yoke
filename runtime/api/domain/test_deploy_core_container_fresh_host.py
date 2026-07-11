"""Fresh-host runtime convergence command-plan tests."""

from __future__ import annotations

import subprocess

from yoke_core.domain.deploy_core_container_remote import (
    _RUNTIME_INSTALL,
    ensure_runtime_packages,
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


def test_runtime_install_command_is_valid_posix_shell() -> None:
    parsed = subprocess.run(
        ["sh", "-n", "-c", _RUNTIME_INSTALL],
        capture_output=True,
        text=True,
        check=False,
    )

    assert parsed.returncode == 0, parsed.stderr


def test_fresh_host_installs_aws_cli_v2_outside_apt() -> None:
    runner = FakeRunner(
        [
            CommandResult(1, "", "runtime missing"),
            CommandResult(0, "", ""),
            CommandResult(0, "", ""),
        ]
    )

    ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    probe, install, enable = _remote_commands(runner)
    assert "command -v aws" in probe
    apt_packages = install.split("apt-get install -y -q ", 1)[1].split(" && ", 1)[0]
    assert "awscli" not in apt_packages.split()
    for package in (
        "ca-certificates",
        "curl",
        "unzip",
        "docker.io",
        "docker-compose-v2",
        "amazon-ecr-credential-helper",
        "nginx",
    ):
        assert package in apt_packages.split()

    assert "AWSCLI_ARCH=aarch64" in install
    assert '"$(dpkg --print-architecture)" = "amd64"' in install
    assert "AWSCLI_ARCH=x86_64" in install
    assert "https://awscli.amazonaws.com/awscli-exe-linux-${AWSCLI_ARCH}.zip" in install
    assert "unzip -q /tmp/awscliv2.zip -d /tmp" in install
    assert "sudo /tmp/aws/install --update" in install
    assert install.count("rm -rf /tmp/aws /tmp/awscliv2.zip") == 2
    assert "systemctl enable --now docker nginx" in enable


def test_existing_host_skips_runtime_install() -> None:
    runner = FakeRunner([CommandResult(0, "", ""), CommandResult(0, "", "")])

    ensure_runtime_packages(runner, _env(), emit=lambda _line: None)

    commands = _remote_commands(runner)
    assert len(commands) == 2
    assert "command -v aws" in commands[0]
    assert all("apt-get" not in command for command in commands)
