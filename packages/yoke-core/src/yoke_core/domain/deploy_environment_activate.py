"""environment-activate executor — wake a target env before deploying to it.

Deployment-flow stage executor (``executor: "environment-activate"``) that
makes the target environment reachable for the stages that follow:

- ensure the env's origin EC2 instance is running (start + wait when the
  env was hibernated), located by its stack-derived ``Name`` tag;
- wait until SSH answers on the origin host.

Aurora Serverless v2 wakes itself on the first connection attempt, so the
database is deliberately not probed here: the core-container deploy's
health window (and any real request) triggers and absorbs the cold
resume. Hibernation policy itself (stage TTL timers) is future flow work;
this stage only guarantees "reachable now".
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Callable, Optional

from yoke_core.domain.deploy_environment_settings import (
    DeployEnvironment,
    DeployEnvironmentError,
    resolve_deploy_environment,
)
from yoke_core.domain.deploy_remote import (
    CommandRunner,
    aws_capability_env,
    run_remote,
)


class EnvironmentActivateError(RuntimeError):
    """Environment activation failed; message carries remediation."""


def _emit(line: str) -> None:
    print(line, flush=True)


def _instance_name_tag(env: DeployEnvironment) -> str:
    # Matches the Name tag webapp_vps_stack.py assigns: "{stack}/VpsInstance".
    stack_reference = env.origin_vps_stack_name.strip()
    if not stack_reference:
        environment_id = f"{env.site_id}-{env.env_name}"
        raise EnvironmentActivateError(
            f"Environment {env.env_name!r} pulumi.origin_vps_stack_name for "
            f"{env.project} is required to locate its standalone VPS instance. "
            "Set it via: yoke projects environment-settings merge --project "
            f"{env.project} --environment-id {environment_id} --set "
            "pulumi.origin_vps_stack_name=<standalone-vps-stack-name>"
        )
    stack_name = stack_reference.rsplit("/", 1)[-1]
    return f"{stack_name}/VpsInstance"


def _describe_origin_instance(
    runner: CommandRunner, env: DeployEnvironment, aws_env: dict
) -> tuple[str, str]:
    """Return (instance_id, state) for the env origin instance."""
    result = runner.run(
        [
            "aws", "ec2", "describe-instances",
            "--filters",
            f"Name=tag:Name,Values={_instance_name_tag(env)}",
            "Name=instance-state-name,Values=pending,running,stopping,stopped",
            "--query",
            "Reservations[].Instances[].[InstanceId,State.Name]",
            "--output", "json",
        ],
        env=aws_env,
        timeout=60,
    )
    if not result.ok:
        raise EnvironmentActivateError(
            "[env-activate] describe-instances failed: "
            + result.stderr.strip()
        )
    try:
        rows = json.loads(result.stdout or "[]")
    except ValueError as exc:
        raise EnvironmentActivateError(
            f"[env-activate] describe-instances returned non-JSON: {exc}"
        ) from exc
    if not rows:
        raise EnvironmentActivateError(
            f"[env-activate] no EC2 instance tagged "
            f"'{_instance_name_tag(env)}' exists; apply the standalone origin "
            f"VPS stack ({env.origin_vps_stack_name}) before activating"
        )
    if len(rows) > 1:
        ids = ", ".join(str(r[0]) for r in rows)
        raise EnvironmentActivateError(
            f"[env-activate] multiple instances match tag "
            f"'{_instance_name_tag(env)}': {ids}; resolve the duplicate "
            "before deploying"
        )
    instance_id, state = rows[0][0], rows[0][1]
    return str(instance_id), str(state)


def ensure_instance_running(
    runner: CommandRunner,
    env: DeployEnvironment,
    aws_env: dict,
    emit: Callable[[str], None] = _emit,
) -> str:
    """Start the origin instance when stopped; return its instance id."""
    instance_id, state = _describe_origin_instance(runner, env, aws_env)
    emit(f"  [env-activate] origin instance {instance_id} is {state}")
    if state == "running":
        return instance_id
    if state in ("stopped", "stopping"):
        emit(f"  [env-activate] starting {instance_id}")
        started = runner.run(
            ["aws", "ec2", "start-instances", "--instance-ids", instance_id],
            env=aws_env,
            timeout=60,
        )
        if not started.ok:
            raise EnvironmentActivateError(
                "[env-activate] start-instances failed: "
                + started.stderr.strip()
            )
    waited = runner.run(
        [
            "aws", "ec2", "wait", "instance-running",
            "--instance-ids", instance_id,
        ],
        env=aws_env,
        timeout=600,
    )
    if not waited.ok:
        raise EnvironmentActivateError(
            f"[env-activate] instance {instance_id} did not reach running: "
            + waited.stderr.strip()
        )
    emit(f"  [env-activate] origin instance {instance_id} running")
    return instance_id


def wait_ssh_reachable(
    runner: CommandRunner,
    env: DeployEnvironment,
    emit: Callable[[str], None] = _emit,
    *,
    timeout_s: int = 180,
    poll_interval_s: float = 6.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Poll SSH on the origin host until it answers or the window closes."""
    deadline = time.monotonic() + timeout_s
    last_error = ""
    while time.monotonic() < deadline:
        try:
            probe = run_remote(runner, env, "echo ssh-ok", timeout=30)
        except subprocess.TimeoutExpired as exc:
            last_error = f"ssh probe timed out after {exc.timeout}s"
            emit("  [env-activate] waiting for ssh...")
            sleeper(poll_interval_s)
            continue
        if probe.ok and "ssh-ok" in probe.stdout:
            emit(f"  [env-activate] ssh reachable on {env.origin_host}")
            return
        last_error = (probe.stderr or probe.stdout).strip()
        emit("  [env-activate] waiting for ssh...")
        sleeper(poll_interval_s)
    raise EnvironmentActivateError(
        f"[env-activate] ssh to {env.ssh_target} not reachable within "
        f"{timeout_s}s: {last_error[-400:]}"
    )


def exec_environment_activate(
    project: str,
    env_name: str,
    *,
    runner: Optional[CommandRunner] = None,
    emit: Callable[[str], None] = _emit,
) -> int:
    """Activate ``project``/``env_name``: instance running + SSH reachable."""
    runner = runner or CommandRunner()
    try:
        env = resolve_deploy_environment(project, env_name)
        if env.activation_state == "render_only":
            raise EnvironmentActivateError(
                f"[env-activate] environment '{env_name}' of project "
                f"'{project}' is declared render_only; its Pulumi stack "
                f"({env.stack_name}) has never been applied"
            )
        aws_env = aws_capability_env(env.project, env.aws_region)
        ensure_instance_running(runner, env, aws_env, emit)
        wait_ssh_reachable(runner, env, emit)
        emit(f"  [env-activate] {env.project}/{env.env_name} is active")
        return 0
    except (EnvironmentActivateError, DeployEnvironmentError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1


def main(argv: Optional[list] = None) -> int:
    """Operator-debug CLI: ``python3 -m ... deploy_environment_activate <project> <env>``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(
            "Usage: python3 -m yoke_core.domain.deploy_environment_activate "
            "<project> <env_name>",
            file=sys.stderr,
        )
        return 2
    return exec_environment_activate(args[0], args[1])


if __name__ == "__main__":
    sys.exit(main())
