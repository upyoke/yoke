"""Provider-aware runtime package convergence for core origin hosts."""

from __future__ import annotations

from typing import Callable

from yoke_core.domain.deploy_core_container_remote_errors import (
    fail_remote_step as _fail,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandRunner, run_remote


_RUNTIME_PROBE = (
    "command -v docker >/dev/null 2>&1"
    " && docker compose version >/dev/null 2>&1"
    " && command -v nginx >/dev/null 2>&1"
    " && command -v docker-credential-ecr-login >/dev/null 2>&1"
    " && command -v aws >/dev/null 2>&1"
)

_BASE_RUNTIME_INSTALL = (
    "sudo env DEBIAN_FRONTEND=noninteractive apt-get update -q"
    " && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " ca-certificates curl unzip amazon-ecr-credential-helper nginx"
)

_DOCKER_PROBE = (
    "command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1"
)

_DOCKER_REPAIR = (
    "if command -v docker >/dev/null 2>&1; then"
    " if dpkg-query -W -f='${Status}' docker-ce 2>/dev/null"
    " | grep -q 'ok installed'"
    " || dpkg-query -W -f='${Status}' containerd.io 2>/dev/null"
    " | grep -q 'ok installed'; then"
    " sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " docker-compose-plugin;"
    " elif dpkg-query -W -f='${Status}' docker.io 2>/dev/null"
    " | grep -q 'ok installed'; then"
    " sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " docker-compose-v2;"
    " else echo 'existing Docker provider is not managed by apt;"
    " install its compatible Compose plugin' >&2; exit 1; fi;"
    " else sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " docker.io docker-compose-v2; fi"
)

_AWS_CLI_PROBE = "command -v aws >/dev/null 2>&1"

_AWS_CLI_INSTALL = (
    "AWSCLI_ARCH=aarch64"
    ' && if [ "$(dpkg --print-architecture)" = "amd64" ]; then'
    " AWSCLI_ARCH=x86_64; fi"
    " && rm -rf /tmp/aws /tmp/awscliv2.zip"
    ' && curl -fsSL "https://awscli.amazonaws.com/'
    'awscli-exe-linux-${AWSCLI_ARCH}.zip" -o /tmp/awscliv2.zip'
    " && unzip -q /tmp/awscliv2.zip -d /tmp"
    " && if [ -d /usr/local/aws-cli ]; then"
    " sudo /tmp/aws/install --bin-dir /usr/local/bin"
    " --install-dir /usr/local/aws-cli --update;"
    " else sudo /tmp/aws/install --bin-dir /usr/local/bin"
    " --install-dir /usr/local/aws-cli; fi"
    " && rm -rf /tmp/aws /tmp/awscliv2.zip"
)


def ensure_runtime_packages(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Converge host tools without replacing a working Docker provider."""
    probe = run_remote(runner, env, _RUNTIME_PROBE, timeout=30)
    if probe.ok:
        emit("  [core-deploy] runtime packages present")
    else:
        emit("  [core-deploy] reconciling runtime packages")
        base = run_remote(runner, env, _BASE_RUNTIME_INSTALL, timeout=600)
        if not base.ok:
            _fail("base runtime package install", base)

        docker_probe = run_remote(runner, env, _DOCKER_PROBE, timeout=30)
        if not docker_probe.ok:
            emit("  [core-deploy] repairing Docker/Compose runtime")
            docker_repair = run_remote(runner, env, _DOCKER_REPAIR, timeout=600)
            if not docker_repair.ok:
                _fail("Docker/Compose runtime repair", docker_repair)

        aws_probe = run_remote(runner, env, _AWS_CLI_PROBE, timeout=30)
        if not aws_probe.ok:
            emit("  [core-deploy] installing AWS CLI v2")
            aws_install = run_remote(runner, env, _AWS_CLI_INSTALL, timeout=600)
            if not aws_install.ok:
                _fail("AWS CLI v2 install", aws_install)

        verify = run_remote(runner, env, _RUNTIME_PROBE, timeout=30)
        if not verify.ok:
            _fail("runtime package verification", verify)

    enable = run_remote(
        runner,
        env,
        "sudo systemctl enable --now docker nginx"
        f" && sudo usermod -aG docker {env.ssh_user}",
        timeout=60,
    )
    if not enable.ok:
        _fail("docker/nginx service enablement", enable)
