"""Origin-host convergence steps for the core-container deploy executor.

Each function converges one aspect of the environment origin host over SSH
and is idempotent: probe first, mutate only when the probe fails, verify
after. The orchestrator (:mod:`yoke_core.domain.deploy_core_container`)
sequences these and translates failures into stage failures.

Remote payloads travel via SSH stdin only — never argv, never a local temp file.
"""

from __future__ import annotations

import json
import shlex
from typing import Callable, List

from yoke_core.domain.deploy_core_container_remote_cleanup import (
    prune_superseded_images,
)
from yoke_core.domain.deploy_core_container_remote_errors import (
    RemoteConvergenceError,
    fail_remote_step as _fail,
)
from yoke_core.domain.deploy_core_container_remote_health import (
    verify_origin_health,
    wait_container_healthy,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import (
    CommandRunner,
    push_remote_file,
    run_remote,
)

__all__ = [
    "RemoteConvergenceError",
    "prune_superseded_images",
    "verify_origin_health",
    "wait_container_healthy",
]


_RUNTIME_PROBE = (
    "command -v docker >/dev/null 2>&1"
    " && docker compose version >/dev/null 2>&1"
    " && command -v nginx >/dev/null 2>&1"
    " && command -v docker-credential-ecr-login >/dev/null 2>&1"
    " && command -v aws >/dev/null 2>&1"
)

_RUNTIME_INSTALL = (
    "sudo env DEBIAN_FRONTEND=noninteractive apt-get update -q"
    " && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " ca-certificates curl unzip docker.io docker-compose-v2"
    " amazon-ecr-credential-helper nginx"
    " && AWSCLI_ARCH=aarch64"
    ' && if [ "$(dpkg --print-architecture)" = "amd64" ]; then'
    " AWSCLI_ARCH=x86_64; fi"
    " && rm -rf /tmp/aws /tmp/awscliv2.zip"
    ' && curl -fsSL "https://awscli.amazonaws.com/'
    'awscli-exe-linux-${AWSCLI_ARCH}.zip" -o /tmp/awscliv2.zip'
    " && unzip -q /tmp/awscliv2.zip -d /tmp"
    " && sudo /tmp/aws/install --update"
    " && rm -rf /tmp/aws /tmp/awscliv2.zip"
)

# IMDSv2-compatible probe that works on IMDSv1-permissive instances too.
_INSTANCE_PROFILE_PROBE = (
    'TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token"'
    ' -H "X-aws-ec2-metadata-token-ttl-seconds: 60" -m 2);'
    ' curl -s -m 2 -H "X-aws-ec2-metadata-token: $TOKEN"'
    " http://169.254.169.254/latest/meta-data/iam/info"
)


def ensure_runtime_packages(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Install docker + compose + ECR credential helper + nginx when absent."""
    probe = run_remote(runner, env, _RUNTIME_PROBE, timeout=30)
    if probe.ok:
        emit("  [core-deploy] runtime packages present")
    else:
        emit(
            "  [core-deploy] installing runtime packages (docker/compose/nginx/ecr-login)"
        )
        install = run_remote(runner, env, _RUNTIME_INSTALL, timeout=600)
        if not install.ok:
            _fail("runtime package install", install)

    enable = run_remote(
        runner,
        env,
        "sudo systemctl enable --now docker nginx"
        f" && sudo usermod -aG docker {env.ssh_user}",
        timeout=60,
    )
    if not enable.ok:
        _fail("docker/nginx service enablement", enable)


def ensure_instance_profile(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Verify the origin instance carries an IAM instance profile.

    The profile grants ECR pull + CloudWatch Logs write + DB secret reads;
    without it, ``docker compose pull``, the ``awslogs`` log driver, or
    runtime DB auth fail later with opaque errors, so this preflight names
    the real fix.
    """
    probe = run_remote(runner, env, _INSTANCE_PROFILE_PROBE, timeout=30)
    if not probe.ok or "InstanceProfileArn" not in probe.stdout:
        _fail(
            "instance profile preflight",
            probe,
            remediation=(
                "the origin EC2 instance has no IAM instance profile; apply "
                f"the environment stack ({env.stack_name}) so the origin "
                "role/profile from webapp_environment_stack.py is attached"
            ),
        )
    emit("  [core-deploy] instance profile present")


def ensure_ecr_credential_helper(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Point the remote docker client at the ECR credential helper."""
    config = json.dumps({"credHelpers": {env.registry_host: "ecr-login"}}, indent=2)
    mkdir = run_remote(runner, env, "mkdir -p ~/.docker", timeout=30)
    if not mkdir.ok:
        _fail("docker config dir creation", mkdir)
    push = push_remote_file(
        runner,
        env,
        content=config + "\n",
        remote_path="~/.docker/config.json",
        mode="600",
        sudo=False,
    )
    if not push.ok:
        _fail("docker credential helper config write", push)
    emit("  [core-deploy] ECR credential helper configured")


def ensure_nginx_site(
    runner: CommandRunner,
    env: DeployEnvironment,
    site_config: str,
    emit: Callable[[str], None],
) -> None:
    """Install the origin nginx site and reload nginx."""
    site_name = f"{env.deploy_namespace}-core.conf"
    push = push_remote_file(
        runner,
        env,
        content=site_config,
        remote_path=f"/etc/nginx/sites-available/{site_name}",
        mode="644",
        sudo=True,
    )
    if not push.ok:
        _fail("nginx site config write", push)

    activate = run_remote(
        runner,
        env,
        f"sudo ln -sf /etc/nginx/sites-available/{site_name}"
        f" /etc/nginx/sites-enabled/{site_name}"
        " && sudo rm -f /etc/nginx/sites-enabled/default"
        " && sudo nginx -t && sudo systemctl reload nginx",
        timeout=60,
    )
    if not activate.ok:
        _fail("nginx site activation", activate)
    emit("  [core-deploy] nginx site converged")


def ensure_compose_project(
    runner: CommandRunner,
    env: DeployEnvironment,
    compose_yaml: str,
    env_file: str,
    emit: Callable[[str], None],
) -> None:
    """Materialize the compose dir, compose file, and env file."""
    prepare = run_remote(
        runner,
        env,
        f"sudo mkdir -p {env.compose_dir}"
        f" && sudo chown {env.ssh_user}:{env.ssh_user} {env.compose_dir}"
        f" && sudo chmod 700 {env.compose_dir}",
        timeout=30,
    )
    if not prepare.ok:
        _fail("compose project dir preparation", prepare)

    compose_push = push_remote_file(
        runner,
        env,
        content=compose_yaml,
        remote_path=f"{env.compose_dir}/docker-compose.yml",
        mode="644",
        sudo=False,
    )
    if not compose_push.ok:
        _fail("compose file write", compose_push)

    env_push = push_remote_file(
        runner,
        env,
        content=env_file,
        remote_path=f"{env.compose_dir}/.env",
        mode="600",
        sudo=False,
    )
    if not env_push.ok:
        raise RemoteConvergenceError(
            f"[core-deploy] service env file write failed (rc={env_push.returncode})"
        )
    emit("  [core-deploy] compose project converged")


def compose_pull(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Pull the pinned image into the compose project."""
    emit("  [core-deploy] docker compose pull")
    pull = run_remote(
        runner,
        env,
        f"cd {env.compose_dir} && docker compose pull",
        timeout=900,
    )
    if not pull.ok:
        _fail("docker compose pull", pull)


def verify_runtime_database_secret_access(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Verify the pulled service image can resolve the managed DB secret."""
    script = (
        "from yoke_core.domain.cloud_db_secret_dsn import "
        "clear_cache, resolve_dsn_from_env; "
        "clear_cache(); resolve_dsn_from_env()"
    )
    probe = run_remote(
        runner,
        env,
        f"cd {env.compose_dir} && docker compose run --rm --no-deps "
        f"--entrypoint python core -c {shlex.quote(script)}",
        timeout=120,
    )
    if not probe.ok:
        _fail(
            "database secret access preflight",
            probe,
            remediation=(
                "the pulled core-service image cannot resolve the environment "
                "database secret through its runtime AWS credentials; apply "
                f"the environment stack ({env.stack_name}) so the origin role "
                "policy includes secretsmanager:GetSecretValue for the "
                "RDS-managed secret"
            ),
        )
    emit("  [core-deploy] database secret access verified")


def compose_up(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """(Re)start the compose service."""
    emit("  [core-deploy] docker compose up -d")
    # --force-recreate: a stale container keeps the previous env binding.
    up = run_remote(
        runner,
        env,
        f"cd {env.compose_dir} && docker compose up -d --remove-orphans --force-recreate",
        timeout=300,
    )
    if not up.ok:
        _fail("docker compose up", up)


def compose_pull_up(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Pull the pinned image and (re)start the service."""
    compose_pull(runner, env, emit)
    compose_up(runner, env, emit)


def remote_step_names() -> List[str]:
    """Stable step vocabulary, used by tests and progress filters."""
    return [
        "runtime packages",
        "instance profile",
        "ecr credential helper",
        "nginx site",
        "compose project",
        "compose pull/up",
        "database secret access",
        "container health",
        "origin health",
    ]
