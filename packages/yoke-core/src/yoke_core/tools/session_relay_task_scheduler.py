"""Per-user interactive Windows relay supervision, without elevation or passwords."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
import os
from pathlib import Path
import subprocess
import time
from typing import Mapping
import xml.etree.ElementTree as ET

from yoke_contracts.direct_database_access import USE_HTTPS_ENV
from yoke_contracts.machine_config import paths as machine_paths
from yoke_core.tools.session_relay_links import create_relay_directory as create_private_directory
from yoke_contracts.owner_private_path import write_owner_private
from yoke_contracts.machine_config.relay_instance import (
    RelayInstance, door_relay_refusal, resolve_relay_instance,
)
from yoke_core.domain.relay_launchd_status import RelayInstallError
from yoke_core.tools import session_relay_release_install as relay_install
from yoke_core.tools.session_relay_release import RelayReleaseError, relay_runtime_python
from yoke_core.tools.session_relay_runtime_install import ensure_relay_runtime
from yoke_core.tools.session_relay_release_retention import release_install_lock
from yoke_contracts.machine_config.relay_instance import WINDOWS_RELAY_RUNNER_ENV
from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.platform_process import process_command_lines
from yoke_core.tools.session_relay_task_stop import wait_relay_task_stopped
from yoke_core.tools.session_relay_task_runner import relay_task_runner_source
from yoke_contracts import windows_task_scheduler as task_scheduler
from yoke_contracts.windows_task_scheduler import Runner, TASK_NS, task_node as node

_COMMAND_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class RelayTaskStatus:
    supported: bool
    task_present: bool
    task_current: bool
    loaded: bool
    task_name: str
    environment: str
    state_dir: Path
    reason: str = ""
    enabled: bool = False


def _run(argv: list[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return task_scheduler.run_command(argv, runner, timeout=_COMMAND_TIMEOUT_SECONDS)
    except task_scheduler.SchedulerCommandError as exc:
        raise _unavailable(str(exc)) from exc


def _unavailable(detail: str) -> RelayInstallError:
    return RelayInstallError(
        compose_refusal(
            f"relay_task_scheduler_unavailable: {detail}",
            recovery="enable Task Scheduler and permit this user's interactive scheduled "
            "tasks, then retry `yoke relay install`",
        ),
        code="relay_task_scheduler_unavailable",
    )


def _checked(argv: list[str], runner: Runner) -> str:
    result = _run(argv, runner)
    if result.returncode:
        raise _unavailable(str(result.stderr or result.stdout or result.returncode).strip())
    return result.stdout.strip()


def _account(runner: Runner) -> tuple[str, str]:
    try:
        return task_scheduler.current_account(runner, timeout=_COMMAND_TIMEOUT_SECONDS)
    except task_scheduler.SchedulerCommandError as exc:
        raise _unavailable(str(exc)) from exc


def relay_task_command(state_dir: Path) -> Path:
    """The windowless interpreter the task runs: the venv's ``pythonw.exe``.

    stdlib ``venv`` writes it beside ``python.exe``. An interactive task
    running ``python.exe`` gets a console window, and closing it kills the relay.
    """
    return relay_runtime_python(state_dir).with_name("pythonw.exe")


def relay_task_document(instance: RelayInstance, *, user_sid: str) -> str:
    root = ET.Element("Task", {"version": "1.2", "xmlns": TASK_NS})
    trigger = node(node(root, "Triggers"), "LogonTrigger")
    node(trigger, "Enabled", "true")
    node(trigger, "UserId", user_sid)
    principal = node(node(root, "Principals"), "Principal", id="RelayUser")
    node(principal, "UserId", user_sid)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(root, "Settings")
    for name, value in {
        "MultipleInstancesPolicy": "IgnoreNew",
        "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false",
        "AllowHardTerminate": "true",
        "StartWhenAvailable": "true",
        "Enabled": "true",
        "ExecutionTimeLimit": "PT0S",
    }.items():
        node(settings, name, value)
    restart = node(settings, "RestartOnFailure")
    node(restart, "Interval", "PT1M")
    node(restart, "Count", "999")
    action = node(node(root, "Actions", Context="RelayUser"), "Exec")
    node(action, "Command", str(relay_task_command(instance.state_dir)))
    node(action, "Arguments", subprocess.list2cmdline(["-I", str(instance.state_dir / "task-runner.py")]))
    node(action, "WorkingDirectory", str(instance.state_dir))
    return ET.tostring(root, encoding="unicode")


#: Task Scheduler schema defaults. An export omits an element holding its
#: default, so an absent element matches a declared default.
_SCHEMA_DEFAULTS = {
    "Enabled": "true",
    "AllowHardTerminate": "true",
    "MultipleInstancesPolicy": "IgnoreNew",
    "RunLevel": "LeastPrivilege",
    "StartWhenAvailable": "false",
    "DisallowStartIfOnBatteries": "true",
    "StopIfGoingOnBatteries": "true",
    "ExecutionTimeLimit": "PT72H",
}


def _difference(observed: str, expected: str, *, account_name: str = "") -> str:
    """Every declared task setting the registered task lacks; empty when current.

    Task Scheduler may add elements to a registered task, so only the settings
    Yoke declares are compared.
    """
    try:
        actual = ET.fromstring(observed)
    except ET.ParseError as exc:
        return f"the registered task XML does not parse ({exc})"

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    def compare(want, have, path: str) -> list[str]:
        text = (want.text or "").strip()
        if have is None:
            return [] if _SCHEMA_DEFAULTS.get(local(want.tag)) == text else [f"{path} is missing"]
        found = [
            f"{path}@{key} is {have.attrib.get(key)!r}, expected {value!r}"
            for key, value in want.attrib.items()
            if have.attrib.get(key) != value
        ]
        observed_text = (have.text or "").strip()
        same_account = local(want.tag) == "UserId" and observed_text.casefold() == account_name.casefold()
        if text != observed_text and not same_account:
            found.append(f"{path} is {observed_text!r}, expected {text!r}")
        for child in want:
            found += compare(child, have.find(child.tag), f"{path}/{local(child.tag)}")
        return found

    desired = ET.fromstring(expected)
    return "; ".join(compare(desired, actual, local(desired.tag)))


def _read_task(label: str, runner: Runner, *, include_xml: bool = False) -> str:
    name = label.replace("'", "''")
    xml = "; $task.Xml" if include_xml else ""
    return _checked([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "$ErrorActionPreference='Stop'; [Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "$s=New-Object -ComObject Schedule.Service; $s.Connect(); $root=$s.GetFolder('\\'); "
        f"try {{ $task=$root.GetTask('{name}') }} catch {{ "
        # HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND) from this named lookup.
        "if ($_.Exception.GetBaseException().HResult -eq 0x80070002) { 'missing'; exit 0 }; "
        f"throw }}; [int]$task.State{xml}",
    ], runner)


def relay_task_state(label: str, runner: Runner) -> str:
    state = _read_task(label, runner)
    if state == "missing":
        raise _unavailable(f"the scheduled task {label} is missing")
    return state


def relay_task_status(*, instance=None, home=None, environ=None, runner=subprocess.run,
                      account: tuple[str, str] | None = None) -> RelayTaskStatus:
    selected = instance or resolve_relay_instance()
    present = current = loaded = enabled = False
    reason = ""
    available = True
    try:
        output = _read_task(selected.label, runner, include_xml=True)
        if output != "missing":
            state, _, xml = output.partition("\n")
            state = state.rstrip("\r")
            if state not in {"0", "1", "2", "3", "4"} or not xml:
                raise _unavailable(f"Task Scheduler returned incomplete status for {selected.label}")
            present = True
            sid, name = account or _account(runner)
            difference = _difference(
                xml, relay_task_document(selected, user_sid=sid), account_name=name
            )
            current = not difference
            loaded = state == "4"
            enabled = state in {"2", "3", "4"}
            if state == "1":
                reason = "relay_task_disabled: enable the task with `yoke relay install`"
        if present and not current and not reason:
            reason = (
                f"relay_task_outdated: {difference}; retry `yoke relay install` "
                "to restore the task settings"
            )
    except RelayInstallError as exc:
        available = False
        reason = str(exc)
    return RelayTaskStatus(available, present, current, loaded, selected.label,
                           selected.environment, selected.state_dir, reason, enabled)


def install_relay_task(*, instance=None, home=None, environ: Mapping[str, str] | None = None,
                       runner= subprocess.run, pin_release=relay_install.pin_relay_release):
    selected = instance or resolve_relay_instance()
    if refusal := door_relay_refusal(selected):
        raise RelayInstallError(refusal, code=USE_HTTPS_ENV)
    account = _account(runner)
    read_status = partial(relay_task_status, instance=selected, runner=runner, account=account)
    prior = read_status()
    if not prior.supported:
        raise RelayInstallError(prior.reason, code="relay_task_scheduler_unavailable")
    try:
        launcher = relay_install.converge_relay_launcher(selected, pin_release=pin_release)
    except RelayReleaseError as exc:
        raise RelayInstallError(str(exc), code=exc.code) from exc
    create_private_directory(selected.state_dir)
    if not selected.follows_served_release:
        # A versioned operator CLI can be retired after an update. The task's
        # interpreter must remain physical and stable, even for local universes.
        with release_install_lock(selected.state_dir):
            ensure_relay_runtime(selected.state_dir)
    source_env = os.environ if environ is None else environ
    environment = {
        machine_paths.CONFIG_FILE_ENV: str(selected.config_path),
        machine_paths.HOME_ENV: str(selected.yoke_home),
        "PATH": source_env.get("PATH", ""),
        WINDOWS_RELAY_RUNNER_ENV: "1",
    }
    if selected.follows_served_release:
        argv = [str(relay_runtime_python(selected.state_dir)), "-I",
                str(relay_runtime_python(selected.state_dir).with_name("yoke.py")),
                "--env", selected.environment, "relay", "serve"]
    else:
        argv = [str(launcher), "--env", selected.environment, "relay", "serve"]
    body = relay_task_runner_source(
        environment=environment, argv=argv, stdout_log=selected.stdout_log,
        stderr_log=selected.stderr_log, contain=os.name == "nt",
    )
    write_owner_private(selected.state_dir / "task-runner.py", body)
    path = selected.state_dir / "task.xml"
    write_owner_private(path, relay_task_document(selected, user_sid=account[0]).encode("utf-16"))
    _checked(["schtasks", "/Create", "/TN", selected.label, "/XML", str(path), "/F"], runner)
    if prior.loaded:
        _checked(["schtasks", "/End", "/TN", selected.label], runner)
    _checked(["schtasks", "/Run", "/TN", selected.label], runner)
    status = read_status()
    deadline = time.monotonic() + 5
    if status.task_current and not status.reason and not status.loaded:
        announce_designed_wait("scheduled relay startup", max_wait_seconds=5, cadence="every 100ms")
    while status.task_current and not status.reason and not status.loaded and time.monotonic() < deadline:
        time.sleep(0.1)
        status = read_status()
    if status.reason or not (status.task_current and status.loaded):
        raise _unavailable(status.reason or "the task did not enter the running state; inspect its history")
    return status


def uninstall_relay_task(*, instance=None, home=None, runner= subprocess.run,
                         processes=process_command_lines):
    selected = instance or resolve_relay_instance()
    status = relay_task_status(instance=selected, runner=runner)
    if not status.supported:
        raise _unavailable(status.reason)
    task_state = None
    if status.task_present and status.loaded:
        _checked(["schtasks", "/End", "/TN", selected.label], runner)
        task_state = partial(relay_task_state, selected.label, runner)
    # End returns before the relay tree exits; files it holds open cannot be removed.
    wait_relay_task_stopped(state_dir=selected.state_dir, task_state=task_state,
                            task_name=selected.label, processes=processes)
    if status.task_present:
        _checked(["schtasks", "/Delete", "/TN", selected.label, "/F"], runner)
    status = relay_task_status(instance=selected, runner=runner)
    if status.reason or status.task_present:
        raise _unavailable(status.reason or "the task remains installed; retry relay uninstall")
    for name in ("task-runner.py", "task.xml"):
        (selected.state_dir / name).unlink(missing_ok=True)
    return status
