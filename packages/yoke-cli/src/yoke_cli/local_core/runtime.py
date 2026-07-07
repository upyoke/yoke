"""Runtime inspection helpers for local-core Docker/Colima operations."""

from __future__ import annotations

from typing import Any, Sequence

from yoke_cli.local_core import docker_plan as dp
from yoke_cli.local_core.runner import CommandResult, CommandRunner


def preflight(
    runner: CommandRunner,
    *,
    system: str,
    check_ports: Sequence[int],
    start_colima: bool = False,
) -> tuple[list[dp.Issue], dict[str, Any]]:
    runtime = runtime_report(runner, system=system, start_colima=start_colima)
    issues: list[dp.Issue] = []
    if system not in {"darwin", "linux"}:
        issues.append(dp.issue(
            "platform_unsupported",
            f"{system} is unsupported",
            "Use macOS with Docker/Colima or Linux with Docker.",
        ))
    docker = runtime["docker"]
    if docker["status"] == "missing":
        issues.append(dp.issue(
            "docker_missing",
            "Docker CLI is not installed",
            "Install Docker Desktop or docker CLI + daemon.",
        ))
    elif docker["status"] == "unavailable":
        issues.append(dp.issue(
            "docker_unavailable",
            "Docker daemon is unavailable",
            runtime.get("guidance") or "Start Docker, then retry.",
        ))
    for port in check_ports:
        if not dp.port_free(port):
            issues.append(dp.issue(
                "port_conflict",
                f"port {port} is already in use",
                "Pick another port with --api-port/--postgres-port.",
            ))
    return issues, runtime


def runtime_report(
    runner: CommandRunner,
    *,
    system: str,
    start_colima: bool = False,
) -> dict[str, Any]:
    docker = runner.run(["docker", "version", "--format", "{{.Server.Version}}"])
    runtime: dict[str, Any] = {
        "platform": system,
        "docker": {
            "status": "available" if docker.returncode == 0 else "unavailable",
            "server_version": docker.stdout.strip() or None,
        },
        "colima": {},
    }
    if docker.returncode == 127:
        runtime["docker"]["status"] = "missing"
    if docker.returncode == 0 or system != "darwin":
        return runtime
    colima = runner.run(["colima", "status"])
    runtime["colima"] = {
        "status": "missing" if colima.returncode == 127 else "available",
        "detail": (colima.stdout or colima.stderr).strip()[:300],
    }
    if start_colima and colima.returncode not in (127,):
        started = runner.run(["colima", "start"], timeout=120)
        runtime["colima"]["start_attempted"] = True
        runtime["colima"]["start_returncode"] = started.returncode
    runtime["guidance"] = (
        "Install Colima or start Docker Desktop, then retry."
        if colima.returncode == 127
        else "Run `colima start` or pass --start-colima when safe."
    )
    return runtime


def run_plan(
    runner: CommandRunner,
    plan: Sequence[Sequence[str]],
    *,
    timeout: int,
    allow_missing: bool = False,
) -> list[CommandResult]:
    results: list[CommandResult] = []
    for cmd in plan:
        result = runner.run(cmd, timeout=timeout)
        results.append(result)
        if result.returncode == 0 or _soft_ok(result, allow_missing):
            continue
        break
    return results


def issues_from_results(
    results: Sequence[CommandResult],
    *,
    allow_missing: bool = False,
) -> list[dp.Issue]:
    issues: list[dp.Issue] = []
    for result in results:
        if result.returncode == 0 or _soft_ok(result, allow_missing):
            continue
        text = (result.stderr or result.stdout).strip()
        issues.append(dp.issue(
            "container_command_failed",
            f"{' '.join(result.args[:3])} exited {result.returncode}",
            text[-500:] or "Inspect Docker and retry.",
        ))
        break
    return issues


def container_statuses(runner: CommandRunner) -> dict[str, dict[str, Any]]:
    return {
        "api": container_status(runner, dp.API_CONTAINER),
        "postgres": container_status(runner, dp.DB_CONTAINER),
    }


def container_status(runner: CommandRunner, name: str) -> dict[str, Any]:
    inspect = runner.run([
        "docker", "inspect", "--format",
        "{{.State.Running}} {{if .State.Health}}{{.State.Health.Status}}{{else}}unknown{{end}}",
        name,
    ])
    if inspect.returncode != 0:
        return {"name": name, "running": False, "health": "missing"}
    parts = inspect.stdout.strip().split()
    return {
        "name": name,
        "running": bool(parts and parts[0] == "true"),
        "health": parts[1] if len(parts) > 1 else "unknown",
    }


def _soft_ok(result: CommandResult, allow_missing: bool) -> bool:
    text = result.stderr or result.stdout
    return " already exists" in text or (allow_missing and "No such container" in text)


__all__ = [
    "container_status",
    "container_statuses",
    "issues_from_results",
    "preflight",
    "run_plan",
    "runtime_report",
]
