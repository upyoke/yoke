"""Run a cloud Test Machine only while a lease holds it.

A Test Machine whose settings record ``cloud_instance_id`` is an EC2
instance the project's aws-admin capability powers from the executing
machine. The lease holder starts it, and waits for its SSH server, before
the first host command. Every client flow that ends a lease then stops each
of the project's cloud machines no lease holds; that sweep also catches a
lease the server released on its own, such as a reaped execution, at the
next release. A queued waiter's reserved turn is a lease, so the machine
keeps running until the last one ends. Machines without the setting are
never touched.
"""

from __future__ import annotations

import json
import socket
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.deploy_remote import (
    DEFAULT_AWS_CAPABILITY_TYPE,
    CommandRunner,
    aws_machine_capability_env,
)
from yoke_core.domain.ec2_instance_power import (
    Ec2InstancePowerError,
    ensure_instance_running,
    has_elastic_ip,
    instance_state,
    stop_instance,
)

SSH_PORT = 22
SSH_WAIT_SECONDS = 300
SSH_POLL_SECONDS = 5.0


def _refused(code: str, detail: str, recovery: str) -> HostControlLocalError:
    return HostControlLocalError(
        code=code, phase="power", detail=detail, recovery_hint=recovery
    )


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _call(function_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )
    if response.success:
        return dict(response.result or {})
    error = response.error
    raise _refused(
        "test_machine_power_read_failed",
        f"{function_id} refused ({error.code if error else 'unknown'}: "
        f"{error.message if error else 'no error'})",
        f"fix the named cause and rerun; `yoke test-machine list --project "
        f"{payload['project']}` must answer",
    )


def _aws_env(project: str) -> dict[str, str]:
    capability = _call(
        "projects.capability_settings.get",
        {"project": project, "cap_type": DEFAULT_AWS_CAPABILITY_TYPE},
    )
    settings = json.loads(str(capability.get("settings_json") or "{}"))
    region = str((settings or {}).get("region") or "").strip()
    try:
        if not region:
            raise RuntimeError("aws-admin capability settings declare no region")
        return aws_machine_capability_env(project, region)
    except RuntimeError as exc:
        raise _refused(
            "test_machine_power_aws_unavailable",
            f"project {project} cannot power its cloud Test Machines: {exc}",
            f"run `yoke aws admin-status --project {project}` and apply its "
            "remedy, then rerun",
        ) from exc


def wait_for_ssh_server(
    name: str,
    host: str,
    emit: Callable[[str], None] = _emit,
    *,
    timeout_s: int = SSH_WAIT_SECONDS,
    connect: Callable[..., Any] = socket.create_connection,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Wait until the host's SSH server sends its banner; no login is tried."""
    announce_designed_wait(
        f"Test Machine {name} SSH server on {host}:{SSH_PORT}",
        max_wait_seconds=timeout_s,
        cadence=poll_every(SSH_POLL_SECONDS),
        write=emit,
    )
    deadline = clock() + timeout_s
    last_error = "no attempt"
    while clock() < deadline:
        try:
            with connect((host, SSH_PORT), timeout=10) as sock:
                banner = sock.recv(64)
            if banner.startswith(b"SSH-"):
                emit(f"  Test Machine {name} SSH server answers on {host}")
                return
            last_error = f"unexpected banner {banner[:24]!r}"
        except OSError as exc:
            last_error = str(exc) or type(exc).__name__
        sleeper(SSH_POLL_SECONDS)
    raise _refused(
        "test_machine_power_ssh_unreachable",
        f"Test Machine {name} is running but {host}:{SSH_PORT} sent no SSH "
        f"banner within {timeout_s}s ({last_error})",
        "confirm the instance's public address still matches the registered "
        "host and its security group admits this machine, then rerun",
    )


def power_on(
    project: str,
    settings: Mapping[str, str],
    *,
    runner: CommandRunner | None = None,
    emit: Callable[[str], None] = _emit,
) -> None:
    """Start a cloud Test Machine for its lease; no-op without an instance id.

    Raises ``HostControlLocalError`` naming the failed step and its recovery.
    """
    instance_id = str(settings.get("cloud_instance_id") or "")
    if not instance_id:
        return
    name = str(settings["resource_name"])
    aws_env = _aws_env(project)
    try:
        prior = ensure_instance_running(
            runner or CommandRunner(), instance_id, aws_env, emit
        )
    except Ec2InstancePowerError as exc:
        raise _refused(
            "test_machine_power_start_failed",
            f"Test Machine {name}: {exc}",
            "fix the named cause, then rerun; read the instance with `yoke aws "
            f"exec --project {project} -- ec2 describe-instances --instance-ids "
            f"{instance_id}`",
        ) from exc
    if prior != "running":
        wait_for_ssh_server(name, str(settings["host"]), emit)


def _stop_if_running(
    runner: CommandRunner,
    project: str,
    settings: Mapping[str, str],
    aws_env: dict[str, str],
    emit: Callable[[str], None],
) -> None:
    name = settings["resource_name"]
    instance_id = settings["cloud_instance_id"]
    try:
        if instance_state(runner, instance_id, aws_env) not in ("pending", "running"):
            return
        if not has_elastic_ip(runner, instance_id, aws_env):
            emit(
                compose_refusal(
                    f"test_machine_power_stop_skipped: idle Test Machine {name} "
                    f"({instance_id}) has no Elastic IP, so a stop would change "
                    f"the public address its registered host {settings['host']} "
                    "names; it stays running",
                    recovery="declare an Elastic IP for the instance in the "
                    "project's infrastructure; the next lease release stops it",
                )
            )
            return
        emit(f"  Test Machine {name} has no lease")
        stop_instance(runner, instance_id, aws_env, emit)
    except Ec2InstancePowerError as exc:
        emit(
            compose_refusal(
                f"test_machine_power_stop_failed: idle Test Machine {name} "
                f"is still running: {exc}",
                recovery="fix the named cause; the next lease release retries, or "
                f"run `yoke aws exec --project {project} -- ec2 stop-instances "
                f"--instance-ids {instance_id}`",
            )
        )


def power_off_idle(
    project: str | None,
    *,
    runner: CommandRunner | None = None,
    emit: Callable[[str], None] = _emit,
) -> None:
    """Stop the project's running cloud Test Machines that no lease holds.

    Called after a flow ends its lease. A failure is printed as a named
    refusal and never replaces the flow's own result. With no selected
    project there is nothing to sweep; the next release in that project does.
    """
    if not project:
        return
    try:
        machines = _call("test_machine.list", {"project": project})["test_machines"]
        idle = [
            machine["settings"]
            for machine in machines
            if machine["settings"].get("cloud_instance_id")
            and machine.get("active_lease") is None
        ]
        if not idle:
            return
        aws_env = _aws_env(project)
    except HostControlLocalError as exc:
        emit(compose_refusal(f"{exc.code}: {exc}", recovery=exc.recovery_hint))
        return
    except Exception as exc:  # noqa: BLE001 - a sweep never masks its flow
        emit(
            compose_refusal(
                f"test_machine_power_sweep_failed: idle cloud Test Machines of "
                f"{project} were not checked ({type(exc).__name__}: {exc})",
                recovery="fix the named cause; the next lease release retries",
            )
        )
        return
    for settings in idle:
        _stop_if_running(runner or CommandRunner(), project, settings, aws_env, emit)


def host_case_projects(cases: list[Mapping[str, Any]]) -> list[str]:
    """Projects whose Test Machines a plan's host-holding cases lease."""
    return sorted(
        {
            str(case["project"])
            for case in cases
            if case.get("project")
            and (
                case.get("runner_id") in ("host_control", "agent_mission")
                or (case.get("method_config") or {}).get("test_machine")
            )
        }
    )


__all__ = [
    "host_case_projects",
    "power_off_idle",
    "power_on",
    "wait_for_ssh_server",
]
