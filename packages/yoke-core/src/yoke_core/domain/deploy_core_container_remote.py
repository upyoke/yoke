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
import time
from typing import Callable, List

from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import (
    CommandResult,
    CommandRunner,
    push_remote_file,
    run_remote,
)


class RemoteConvergenceError(RuntimeError):
    """A box-convergence step failed; message carries remediation."""


_RUNTIME_PROBE = (
    "command -v docker >/dev/null 2>&1"
    " && docker compose version >/dev/null 2>&1"
    " && command -v nginx >/dev/null 2>&1"
    " && command -v docker-credential-ecr-login >/dev/null 2>&1"
)

_RUNTIME_INSTALL = (
    "sudo env DEBIAN_FRONTEND=noninteractive apt-get update -q"
    " && sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q"
    " docker.io docker-compose-v2 amazon-ecr-credential-helper nginx"
)

# IMDSv2-compatible probe that works on IMDSv1-permissive instances too.
_INSTANCE_PROFILE_PROBE = (
    'TOKEN=$(curl -sX PUT "http://169.254.169.254/latest/api/token"'
    ' -H "X-aws-ec2-metadata-token-ttl-seconds: 60" -m 2);'
    ' curl -s -m 2 -H "X-aws-ec2-metadata-token: $TOKEN"'
    " http://169.254.169.254/latest/meta-data/iam/info"
)


def _fail(step: str, result: CommandResult, remediation: str = "") -> None:
    detail = (result.stderr or result.stdout).strip()
    message = f"[core-deploy] {step} failed (rc={result.returncode})"
    if detail:
        message += f": {detail[-800:]}"
    if remediation:
        message += f"\n  remediation: {remediation}"
    raise RemoteConvergenceError(message)


def ensure_runtime_packages(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Install docker + compose + ECR credential helper + nginx when absent."""
    probe = run_remote(runner, env, _RUNTIME_PROBE, timeout=30)
    if probe.ok:
        emit("  [core-deploy] runtime packages present")
    else:
        emit("  [core-deploy] installing runtime packages (docker/compose/nginx/ecr-login)")
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
    config = json.dumps(
        {"credHelpers": {env.registry_host: "ecr-login"}}, indent=2
    )
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


def wait_container_healthy(
    runner: CommandRunner,
    env: DeployEnvironment,
    container_name: str,
    emit: Callable[[str], None],
    *,
    timeout_s: int = 240,
    poll_interval_s: float = 5.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll the container health status until healthy or timeout.

    The window is generous on purpose: first request after an Aurora
    scale-to-zero pause adds a cold-resume delay on top of the container
    start period.
    """
    deadline = time.monotonic() + timeout_s
    last_status = "unknown"
    while time.monotonic() < deadline:
        probe = run_remote(
            runner,
            env,
            "docker inspect --format '{{.State.Health.Status}}' "
            + container_name,
            timeout=30,
        )
        last_status = (probe.stdout or probe.stderr).strip() or "unknown"
        if probe.ok and last_status == "healthy":
            emit(f"  [core-deploy] container {container_name} healthy")
            return
        if probe.ok and last_status == "unhealthy":
            logs = run_remote(
                runner,
                env,
                f"docker logs --tail 40 {container_name}",
                timeout=30,
            )
            tail = (logs.stdout + logs.stderr).strip()[-1200:]
            raise RemoteConvergenceError(
                f"[core-deploy] container {container_name} reported unhealthy"
                + (f"; recent logs:\n{tail}" if tail else "")
            )
        emit(
            f"  [core-deploy] waiting for container health (status: {last_status})"
        )
        sleeper(poll_interval_s)
    raise RemoteConvergenceError(
        f"[core-deploy] container {container_name} did not become healthy "
        f"within {timeout_s}s (last status: {last_status})"
    )


def verify_origin_health(
    runner: CommandRunner,
    env: DeployEnvironment,
    request_id: str,
    emit: Callable[[str], None],
) -> None:
    """Hit the health endpoint through nginx on the box, asserting request-id echo."""
    check = run_remote(
        runner,
        env,
        f'curl -fsS -m 15 -D - -H "x-request-id: {request_id}" '
        f"http://127.0.0.1:{env.origin_port}{env.health_path}",
        timeout=30,
    )
    if not check.ok:
        _fail("origin nginx health check", check)
    headers = check.stdout.lower()
    if f"x-request-id: {request_id}".lower() not in headers:
        raise RemoteConvergenceError(
            "[core-deploy] origin health response did not echo x-request-id "
            f"'{request_id}'; request-id propagation is part of the deploy "
            "contract (request-id propagation)"
        )
    body = _http_body(check.stdout)
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RemoteConvergenceError(
            "[core-deploy] origin health response was not JSON"
        ) from exc
    if payload.get("schema_ready") is not True:
        missing = payload.get("schema_missing_tables")
        detail = (
            f" (missing tables: {missing})"
            if isinstance(missing, list) and missing
            else ""
        )
        raise RemoteConvergenceError(
            "[core-deploy] origin health did not report schema_ready=true"
            + detail
        )
    emit(
        f"  [core-deploy] origin health ok (request-id {request_id} echoed)"
    )


def _http_body(raw: str) -> str:
    if "\r\n\r\n" in raw:
        return raw.rsplit("\r\n\r\n", 1)[1].strip()
    if "\n\n" in raw:
        return raw.rsplit("\n\n", 1)[1].strip()
    return raw.strip()


def prune_superseded_images(
    runner: CommandRunner, env: DeployEnvironment, emit: Callable[[str], None]
) -> None:
    """Reclaim disk by dropping images no longer referenced by a container.

    Every deploy pulls a fresh ~1.5GB ``yoke-core:<sha>`` image; with no
    prune, superseded images accumulate on the origin box's small root volume
    until ``docker compose pull`` fails with ``no space left on device``. This
    runs only after the new image is deployed and health-verified, so the
    running image (referenced by the live container) is kept while every prior
    image is dropped — the box holds one image at rest, two mid-deploy. Older
    rollback targets stay pullable from the registry.

    Best-effort by design: the deploy has already succeeded and reported
    healthy by the time this runs, so any prune failure (SSH hiccup, timeout,
    docker error) is logged and swallowed — never turned into a deploy failure.
    Runs without ``sudo`` to match ``compose_pull_up``; the deploy user is in
    the ``docker`` group after runtime-package convergence.
    """
    try:
        prune = run_remote(
            runner, env, "docker image prune --all --force", timeout=120
        )
    except Exception as exc:  # noqa: BLE001 — post-success cleanup is best-effort
        emit(
            f"  [core-deploy] image prune skipped ({exc.__class__.__name__}); "
            "disk not reclaimed this deploy"
        )
        return
    if not prune.ok:
        emit(
            "  [core-deploy] image prune skipped "
            f"(rc={prune.returncode}); disk not reclaimed this deploy"
        )
        return
    reclaimed = ""
    for line in reversed((prune.stdout or "").splitlines()):
        if "Total reclaimed space" in line:
            reclaimed = f" ({line.strip()})"
            break
    emit(f"  [core-deploy] pruned superseded images{reclaimed}")


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
