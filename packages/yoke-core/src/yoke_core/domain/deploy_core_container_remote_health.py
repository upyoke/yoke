"""Container and origin health gates for core-container remote deploys."""

from __future__ import annotations

import json
import time
from typing import Callable

from yoke_core.domain.deploy_core_container_remote_errors import (
    RemoteConvergenceError,
    fail_remote_step,
)
from yoke_core.domain.deploy_environment_settings import DeployEnvironment
from yoke_core.domain.deploy_remote import CommandRunner, run_remote


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
    """Poll container health until healthy, unhealthy, or timeout."""
    deadline = time.monotonic() + timeout_s
    last_status = "unknown"
    while time.monotonic() < deadline:
        probe = run_remote(
            runner,
            env,
            "docker inspect --format '{{.State.Health.Status}}' " + container_name,
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
        emit(f"  [core-deploy] waiting for container health (status: {last_status})")
        sleeper(poll_interval_s)
    raise RemoteConvergenceError(
        f"[core-deploy] container {container_name} did not become healthy "
        f"within {timeout_s}s (last status: {last_status})"
    )


def verify_origin_health(
    runner: CommandRunner,
    env: DeployEnvironment,
    request_id: str,
    expected_build: str,
    emit: Callable[[str], None],
) -> None:
    """Assert request routing, schema readiness, and exact release identity."""
    check = run_remote(
        runner,
        env,
        f'curl -fsS -m 15 -D - -H "x-request-id: {request_id}" '
        f"http://127.0.0.1:{env.origin_port}{env.health_path}",
        timeout=30,
    )
    if not check.ok:
        fail_remote_step("origin nginx health check", check)
    headers = check.stdout.lower()
    if f"x-request-id: {request_id}".lower() not in headers:
        raise RemoteConvergenceError(
            "[core-deploy] origin health response did not echo x-request-id "
            f"'{request_id}'; request-id propagation is part of the deploy "
            "contract (request-id propagation)"
        )
    try:
        payload = json.loads(_http_body(check.stdout))
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
            "[core-deploy] origin health did not report schema_ready=true" + detail
        )
    served_build = payload.get("build")
    engine_version = payload.get("engine_version")
    if (
        served_build != expected_build
        or not isinstance(engine_version, str)
        or not engine_version
    ):
        raise RemoteConvergenceError(
            "[core-deploy] origin health release identity mismatch: "
            f"build={served_build!r} engine_version={engine_version!r}, "
            f"expected build={expected_build!r} with a non-empty engine version"
        )
    emit(
        "  [core-deploy] origin health ok "
        f"(request-id {request_id} echoed, build {served_build}, "
        f"engine {engine_version})"
    )


def _http_body(raw: str) -> str:
    if "\r\n\r\n" in raw:
        return raw.rsplit("\r\n\r\n", 1)[1].strip()
    if "\n\n" in raw:
        return raw.rsplit("\n\n", 1)[1].strip()
    return raw.strip()
