"""Start a leased cloud Test Machine with its declared power-project credentials."""

from __future__ import annotations

from yoke_contracts.runtime_ports.test_machine_remote_exec import (
    get_test_machine_remote_exec,
)

import json
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol
from yoke_contracts.azure_admin import AzureAdminError, azure_session
from yoke_contracts.azure_cli_prerequisite import AzureCliPrerequisiteError
from typing import Any

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError
from yoke_contracts.machine_config.capability_secret_store import (
    test_machine_secret_path,
)
from yoke_core.domain.deploy_remote import (
    DEFAULT_AWS_CAPABILITY_TYPE,
    CommandRunner,
    aws_machine_capability_env,
)
from yoke_core.domain.ec2_instance_power import (
    Ec2InstancePowerError,
)

SSH_WAIT_SECONDS = 600
SSH_LOGIN_SECONDS = 60
SSH_POLL_SECONDS = 10.0
SSH_PROBE_OPTIONS = (
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


_power_scope: ContextVar[dict[str, Any] | None] = ContextVar(
    "test_machine_power_dispatch_scope", default=None
)


@contextmanager
def power_dispatch_scope(*, actor=None, relay_env=None):
    """Use the releasing or acquiring call's identity and universe for power writes."""
    scope = {key: value for key, value in {"actor": actor, "relay_env": relay_env}.items() if value is not None}
    token = _power_scope.set(scope)
    try:
        yield
    finally:
        _power_scope.reset(token)


def _dispatch(function_id: str, payload: dict[str, Any]) -> Any:
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch

    build_actor = get_structured_dispatch().build_actor
    call_dispatcher = get_structured_dispatch().call_dispatcher

    options = dict(_power_scope.get() or {})
    if "actor" not in options:
        options["actor"] = build_actor()
    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        **options,
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
        "fix the named cause and retry from the current Yoke CLI",
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
    """The login probe and its stdin: on a WSL host, the WSL Python host facts use.

    A freshly booted Windows host accepts a login long before WSL can start
    Python inside the 20 seconds host control allows its first command.
    """
    if os_name == "windows":
        return (
            'powershell.exe -NoLogo -NoProfile -NonInteractive -Command "exit 0"',
            None,
        )
    if os_name != "wsl":
        return "exit", None
    from yoke_contracts.windows_wsl_command import (
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
    key = test_machine_secret_path(
        settings["resource_name"], "ssh_private_key"
    )
    if not key.exists():
        return
    name, host = settings["resource_name"], settings["host"]
    argv = ["ssh", "-i", str(key)]
    argv += [part for option in SSH_PROBE_OPTIONS for part in ("-o", option)]
    host_key_options = get_test_machine_remote_exec().host_key_options

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
        "confirm Tailscale is running, the controller resolves the registered "
        "MagicDNS name and sshd is running, then rerun",
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
    detail = _call("test_machine.get", {"test_machine": name})
    project = detail.get("power_project")
    if not project or detail.get("settings", {}).get("cloud_instance_id") != instance_id:
        raise _refused(
            "test_machine_power_registration_changed",
            f"Test Machine {name} has no power project or its cloud instance changed",
            "read the current settings with yoke test-machine get and retry",
        )
    read_command = (
        f"yoke {settings.get('cloud_provider', 'aws')} admin-status --project {project}"
    )
    try:
        with machine_power(
            project, settings, runner or CommandRunner(), emit
        ) as provider:
            read_command = provider.read_command
            prior = provider.start()
    except (Ec2InstancePowerError, AzureAdminError, AzureCliPrerequisiteError) as exc:
        raise _refused(
            "test_machine_power_start_failed",
            f"Test Machine {name}: {exc}",
            f"fix the named cause and rerun; inspect it with `{read_command}`",
        ) from exc
    if prior not in {"running", "pending", "VM starting"}:
        _call("test_machine.power_started", {"test_machine": name})
    if prior != "running":
        wait_for_ssh_login(project, settings, emit, runner=runner)
    return


class CloudMachinePower(Protocol):
    """Manage a leased VM and provide commands for operator recovery."""

    @property
    def read_command(self) -> str: ...

    @property
    def stop_command(self) -> str: ...

    def start(self) -> str: ...

    def stop(self) -> None: ...


@contextmanager
def machine_power(
    project: str,
    settings: Mapping[str, str],
    runner: CommandRunner,
    emit: Callable[[str], None],
) -> Iterator[CloudMachinePower]:
    provider = settings.get("cloud_provider", "aws")
    instance_id = settings["cloud_instance_id"]
    if provider == "aws":
        from yoke_core.domain.ec2_machine_power import Ec2MachinePower

        yield Ec2MachinePower(runner, _aws_env(project), instance_id, project, emit)
    elif provider == "azure":
        from yoke_core.domain.azure_instance_power import AzureMachinePower

        capability = _call(
            "projects.capability_settings.get",
            {"project": project, "cap_type": "azure-admin"},
        )
        config = json.loads(str(capability.get("settings_json") or "{}"))
        subscription = str(config.get("subscription_id") or "")
        if not subscription or not instance_id.lower().startswith(
            f"/subscriptions/{subscription}/".lower()
        ):
            raise AzureAdminError(
                "VM resource id names a different subscription; correct azure-admin or the VM id and retry"
            )
        with azure_session(project, config, run=runner.run) as (command, env):
            yield AzureMachinePower(runner, command, env, instance_id, project, emit)
    else:
        raise _refused(
            "test_machine_cloud_provider_unsupported",
            f"unknown provider {provider}",
            "set cloud_provider to aws or azure and retry",
        )


__all__ = [
    "power_on",
    "wait_for_ssh_login",
]
