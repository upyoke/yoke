"""Run a cloud Test Machine only while a lease holds it.

A Test Machine whose settings record ``cloud_instance_id`` is an EC2
instance the project's aws-admin capability powers from the executing
machine. The lease holder starts it, and waits until its key logs in, before
the first host command. When the flow that leased it ends, the process stops
it unless another lease now holds it; a queued waiter's reserved turn is a
lease, so the machine runs until the last one ends. A lease the server
releases with no client flow ending (a reaped execution, a manual claim
release) leaves the machine running until its next lease ends. Machines
without the setting are never touched.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.capability_secrets import TEST_MACHINE_CAPABILITY
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.capability_machine_secrets import (
    machine_capability_secret_path,
)
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

SSH_WAIT_SECONDS = 600
SSH_LOGIN_SECONDS = 60
SSH_POLL_SECONDS = 10.0
SSH_PROBE_OPTIONS = (
    "StrictHostKeyChecking=accept-new",
    "UserKnownHostsFile=/dev/null",
    "LogLevel=ERROR",
    "ConnectTimeout=10",
    "BatchMode=yes",
)


def _refused(code: str, detail: str, recovery: str) -> HostControlLocalError:
    return HostControlLocalError(
        code=code, phase="power", detail=detail, recovery_hint=recovery
    )


# Cloud machines this process started or found running for a lease, keyed by
# (project, resource_name); power_off_released settles them at the flow's end.
_powered: dict[tuple[str, str], dict[str, str]] = {}


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
        f"fix the named cause and rerun; `yoke test-machine get --project "
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


def wait_for_ssh_login(
    project: str,
    settings: Mapping[str, str],
    emit: Callable[[str], None] = _emit,
    *,
    runner: CommandRunner | None = None,
    timeout_s: int = SSH_WAIT_SECONDS,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Retry a key login until it succeeds; a freshly booted host is slow to log in.

    Without the machine-local key there is nothing to try: the host-control
    runner then refuses with its own credential recovery.
    """
    key = machine_capability_secret_path(
        project, TEST_MACHINE_CAPABILITY, "ssh_private_key"
    )
    if not key.exists():
        return
    name, host = settings["resource_name"], settings["host"]
    argv = ["ssh", "-i", str(key)]
    argv += [part for option in SSH_PROBE_OPTIONS for part in ("-o", option)]
    argv += [f"{settings['user']}@{host}", "exit"]
    announce_designed_wait(
        f"Test Machine {name} to accept an SSH login on {host}",
        max_wait_seconds=timeout_s,
        cadence=poll_every(SSH_POLL_SECONDS),
        write=emit,
    )
    deadline = clock() + timeout_s
    last_error = "no attempt"
    while clock() < deadline:
        try:
            result = (runner or CommandRunner()).run(argv, timeout=SSH_LOGIN_SECONDS)
        except subprocess.TimeoutExpired:
            last_error = f"login timed out after {SSH_LOGIN_SECONDS}s"
        else:
            if result.ok:
                emit(f"  Test Machine {name} accepts SSH logins on {host}")
                return
            last_error = (result.stderr or result.stdout).strip()[-300:] or (
                f"ssh exited {result.returncode}"
            )
        sleeper(SSH_POLL_SECONDS)
    raise _refused(
        "test_machine_power_ssh_unreachable",
        f"Test Machine {name} is running but refused SSH logins on {host} for "
        f"{timeout_s}s ({last_error})",
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
    _powered[(project, name)] = dict(settings)
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
        wait_for_ssh_login(project, settings, emit, runner=runner)


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
                    "project's infrastructure; its next lease release stops it",
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
                recovery="fix the named cause; its next lease release retries, or "
                f"run `yoke aws exec --project {project} -- ec2 stop-instances "
                f"--instance-ids {instance_id}`",
            )
        )


def power_off_released(
    *,
    runner: CommandRunner | None = None,
    emit: Callable[[str], None] = _emit,
) -> None:
    """Stop each cloud machine this process powered once its last lease ends.

    Called after a flow ends its lease. A machine another lease (or a queued
    waiter's reserved turn) now holds keeps running. A failure is printed as
    a named refusal and never replaces the flow's own result.
    """
    while _powered:
        (project, name), settings = _powered.popitem()
        try:
            detail = _call("test_machine.get", {"project": project, "test_machine": name})
            if detail.get("active_lease") is not None:
                continue
            _stop_if_running(
                runner or CommandRunner(), project, settings, _aws_env(project), emit
            )
        except HostControlLocalError as exc:
            emit(compose_refusal(f"{exc.code}: {exc}", recovery=exc.recovery_hint))
        except Exception as exc:  # noqa: BLE001 - a stop never masks its flow
            emit(
                compose_refusal(
                    f"test_machine_power_stop_failed: Test Machine {name} may still "
                    f"be running ({type(exc).__name__}: {exc})",
                    recovery=f"run `yoke test-machine verify --project {project} "
                    f"--test-machine {name}`, whose release stops it",
                )
            )


__all__ = [
    "power_off_released",
    "power_on",
    "wait_for_ssh_login",
]
