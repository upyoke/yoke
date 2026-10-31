"""Run a cloud Test Machine only while a lease holds it.

A Test Machine whose settings record ``cloud_instance_id`` is an EC2
instance the project's aws-admin capability powers from the executing
machine. The lease holder starts it, and waits until its key logs in, before
the first host command. The last lease release stops it: any call whose
release leaves the host free (no waiter's turn reserved) names it on its
response (``cloud_machine_release_notice``), and the calling client, whatever
command or process it is, stops it while holding the host's own lease.
A release no client hears (a server-side reap) leaves the host running
until its next lease cycles; by operator choice there is no sweep.
Each power-on reads the instance's current public IPv4 and rebinds its
registered host before SSH. Machines without the setting are never touched.
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
from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError
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
    instance_public_address,
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


def _emit(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _dispatch(function_id: str, payload: dict[str, Any]) -> Any:
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
    )

    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(),
    )


def _call(function_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = _dispatch(function_id, payload)
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


def _readiness_command(os_name: str) -> tuple[str, str | None]:
    """The login probe and its stdin: on Windows, the WSL Python host facts use.

    A freshly booted Windows host accepts a login long before WSL can start
    Python inside the 20 seconds host control allows its first command.
    """
    if os_name != "windows":
        return "exit", None
    from yoke_harness.windows_wsl_command import (
        windows_wsl_command,
        windows_wsl_input,
    )

    reader, framed = windows_wsl_input("/usr/bin/python3 -c pass", None)
    return windows_wsl_command(reader), framed


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
    """Retry a key login until it succeeds; a freshly booted host is slow to answer.

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
    from yoke_harness.test_machine_remote_exec import host_key_options

    argv += host_key_options(settings)
    command, probe_input = _readiness_command(settings["os"])
    argv += [f"{settings['user']}@{host}", command]
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
            result = (runner or CommandRunner()).run(
                argv, input_text=probe_input, timeout=SSH_LOGIN_SECONDS
            )
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
        SSH_UNAVAILABLE,
        f"Test Machine {name} is running but refused SSH logins on {host} for "
        f"{timeout_s}s ({last_error})",
        "confirm the instance's security group admits this machine "
        "and sshd is running, then rerun",
    )


def power_on(
    project: str,
    settings: Mapping[str, str],
    *,
    runner: CommandRunner | None = None,
    emit: Callable[[str], None] = _emit,
) -> Mapping[str, str]:
    """Start a cloud Test Machine for its lease; no-op without an instance id.

    Raises ``HostControlLocalError`` naming the failed step and its recovery.
    """
    instance_id = str(settings.get("cloud_instance_id") or "")
    if not instance_id:
        return settings
    name = str(settings["resource_name"])
    aws_env = _aws_env(project)
    try:
        prior = ensure_instance_running(
            runner or CommandRunner(), instance_id, aws_env, emit
        )
        address = instance_public_address(
            runner or CommandRunner(), instance_id, aws_env
        )
    except Ec2InstancePowerError as exc:
        raise _refused(
            "test_machine_power_start_failed",
            f"Test Machine {name}: {exc}",
            "fix the named cause, then rerun; read the instance with `yoke aws "
            f"exec --project {project} -- ec2 describe-instances --instance-ids "
            f"{instance_id}`",
        ) from exc
    if address is None:
        raise _refused(
            "test_machine_power_no_public_address",
            f"Test Machine {name} instance {instance_id} has no public IPv4",
            "give the instance a public IPv4 (a subnet that assigns one), then rerun; "
            f"read it with `yoke aws exec --project {project} -- ec2 "
            f"describe-instances --instance-ids {instance_id}`",
        )
    if address != settings["host"]:
        current = _call("test_machine.get", {"project": project, "test_machine": name})
        if current["settings"]["host"] != address:
            response = _dispatch(
                "test_machine.host_rebind",
                {
                    "project": project,
                    "test_machine": name,
                    "host": address,
                    "base_settings": current["settings_token"],
                },
            )
            if not response.success:
                error = response.error
                raise _refused(
                    "test_machine_host_rebind_refused",
                    f"{error.code if error else 'unknown'}: "
                    f"{error.message if error else 'no error'}",
                    "fix the named server refusal, re-read the Test Machine and rerun",
                )
            emit(
                f"Test Machine {name} moved from {settings['host']} to {address}; "
                f"its registered host now names {address}"
            )
        settings = {**settings, "host": address}
    if prior != "running":
        wait_for_ssh_login(project, settings, emit, runner=runner)
    return settings


__all__ = [
    "power_on",
    "wait_for_ssh_login",
]
