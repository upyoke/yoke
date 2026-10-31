"""Start and stop one EC2 instance, named by its instance id.

Deploy environments and cloud Test Machines both power hosts through these
calls; each caller resolves its own instance id and AWS child env first.
The AWS CLI runs through the given ``CommandRunner`` so tests substitute it.
"""

from __future__ import annotations

import json
from typing import Callable, Sequence

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_core.domain.deploy_remote import CommandResult, CommandRunner

AWS_CLI_INSTALL_DOCS_URL = (
    "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
)
WAIT_SECONDS = 600


class Ec2InstancePowerError(RuntimeError):
    """An EC2 power call failed; the message names the instance and cause."""


def _run(
    runner: CommandRunner, argv: Sequence[str], aws_env: dict, timeout: int
) -> CommandResult:
    try:
        return runner.run(["aws", "ec2", *argv], env=aws_env, timeout=timeout)
    except OSError as exc:
        raise Ec2InstancePowerError(
            f"the aws CLI could not run ({exc}); install it ({AWS_CLI_INSTALL_DOCS_URL}) "
            "and check it with `yoke aws preflight`"
        ) from exc


def _require_ok(result: CommandResult, instance_id: str, action: str) -> None:
    if not result.ok:
        raise Ec2InstancePowerError(
            f"instance {instance_id}: {action} failed: {result.stderr.strip()}"
        )


def instance_state(runner: CommandRunner, instance_id: str, aws_env: dict) -> str:
    """Return the instance's state name (running, stopped, ...)."""
    described = _run(
        runner,
        [
            "describe-instances",
            "--instance-ids",
            instance_id,
            "--query",
            "Reservations[].Instances[].State.Name",
            "--output",
            "json",
        ],
        aws_env,
        60,
    )
    _require_ok(described, instance_id, "describe-instances")
    try:
        states = json.loads(described.stdout or "[]")
    except ValueError as exc:
        raise Ec2InstancePowerError(
            f"instance {instance_id}: describe-instances returned non-JSON: {exc}"
        ) from exc
    if len(states) != 1:
        raise Ec2InstancePowerError(
            f"instance {instance_id}: describe-instances matched {len(states)} "
            "instances; check the recorded instance id"
        )
    return str(states[0])


def _wait(
    runner: CommandRunner,
    instance_id: str,
    aws_env: dict,
    target: str,
    emit: Callable[[str], None],
) -> None:
    announce_designed_wait(
        f"instance {instance_id} to reach {target} (aws ec2 wait)",
        max_wait_seconds=WAIT_SECONDS,
        cadence=poll_every(15),
        write=emit,
    )
    waited = _run(
        runner,
        ["wait", f"instance-{target}", "--instance-ids", instance_id],
        aws_env,
        WAIT_SECONDS,
    )
    _require_ok(waited, instance_id, f"wait instance-{target}")


def ensure_instance_running(
    runner: CommandRunner,
    instance_id: str,
    aws_env: dict,
    emit: Callable[[str], None],
) -> str:
    """Start the instance unless it runs; return the state it was found in."""
    state = instance_state(runner, instance_id, aws_env)
    emit(f"  instance {instance_id} is {state}")
    if state == "running":
        return state
    if state not in ("pending", "stopping", "stopped"):
        raise Ec2InstancePowerError(
            f"instance {instance_id} is {state} and cannot be started"
        )
    if state == "stopping":
        _wait(runner, instance_id, aws_env, "stopped", emit)
    if state != "pending":
        emit(f"  starting instance {instance_id}")
        started = _run(
            runner, ["start-instances", "--instance-ids", instance_id], aws_env, 60
        )
        _require_ok(started, instance_id, "start-instances")
    _wait(runner, instance_id, aws_env, "running", emit)
    emit(f"  instance {instance_id} running")
    return state


def instance_public_address(
    runner: CommandRunner, instance_id: str, aws_env: dict
) -> str | None:
    """Read the instance's current public IPv4; a private-only instance has none."""
    # map preserves nulls; a projection silently drops a private-only instance.
    described = _run(
        runner,
        [
            "describe-instances",
            "--instance-ids",
            instance_id,
            "--query",
            "map(&PublicIpAddress, Reservations[].Instances[])",
            "--output",
            "json",
        ],
        aws_env,
        60,
    )
    _require_ok(described, instance_id, "describe-instances")
    try:
        addresses = json.loads(described.stdout or "[]")
    except ValueError as exc:
        raise Ec2InstancePowerError(
            f"instance {instance_id}: describe-instances returned non-JSON: {exc}"
        ) from exc
    if not isinstance(addresses, list) or len(addresses) != 1:
        raise Ec2InstancePowerError(
            f"instance {instance_id}: describe-instances must match one instance; "
            "check the recorded instance id"
        )
    return str(addresses[0]) if addresses[0] is not None else None


def stop_instance(
    runner: CommandRunner,
    instance_id: str,
    aws_env: dict,
    emit: Callable[[str], None],
) -> None:
    """Ask EC2 to stop the instance; a later start waits out ``stopping``."""
    stopped = _run(
        runner, ["stop-instances", "--instance-ids", instance_id], aws_env, 60
    )
    _require_ok(stopped, instance_id, "stop-instances")
    emit(f"  stopping instance {instance_id}")


__all__ = [
    "Ec2InstancePowerError",
    "ensure_instance_running",
    "instance_public_address",
    "instance_state",
    "stop_instance",
]
