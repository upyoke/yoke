"""Per-user interactive Windows relay supervision, without elevation or passwords."""

from __future__ import annotations

from dataclasses import dataclass
import locale
import os
from pathlib import Path
import subprocess
import time
from typing import Callable, Mapping
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

Runner = Callable[..., subprocess.CompletedProcess[str]]
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"
LOGIN_BEHAVIOR = (
    "Stops at sign-out; unavailable after reboot until this user logs in; "
    "starts at the next login. Locking the desktop keeps the relay running."
)


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


def _run(argv: list[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(argv, check=False, capture_output=True, timeout=15)
        def decode(value):
            if not isinstance(value, bytes):
                return value or ""
            if value.startswith((b"\xff\xfe", b"\xfe\xff")):
                return value.decode("utf-16")
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return value.decode(locale.getpreferredencoding(False), errors="replace")
        return subprocess.CompletedProcess(argv, result.returncode, decode(result.stdout), decode(result.stderr))
    except (OSError, subprocess.SubprocessError) as exc:
        raise _unavailable(str(exc)) from exc


def _unavailable(detail: str) -> RelayInstallError:
    return RelayInstallError(
        f"relay_task_scheduler_unavailable: {detail}. Recovery: enable Task Scheduler "
        "and permit this user's interactive scheduled tasks, then retry `yoke relay install`.",
        code="relay_task_scheduler_unavailable",
    )


def _checked(argv: list[str], runner: Runner) -> str:
    result = _run(argv, runner)
    if result.returncode:
        raise _unavailable(str(result.stderr or result.stdout or result.returncode).strip())
    return result.stdout.strip()


def _user(runner: Runner) -> str:
    # The SID is stable across renames and avoids locale-dependent account names.
    import csv

    rows = list(csv.reader(_checked(["whoami", "/user", "/fo", "csv", "/nh"], runner).splitlines()))
    if not rows or len(rows[0]) != 2 or not rows[0][1].startswith("S-1-"):
        raise _unavailable("cannot resolve the current user's SID")
    return rows[0][1]


def relay_task_document(instance: RelayInstance, *, user_sid: str) -> str:
    root = ET.Element("Task", {"version": "1.2", "xmlns": TASK_NS})

    def node(parent, name, text=None, **attributes):
        child = ET.SubElement(parent, name, attributes)
        child.text = text
        return child

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
    python = relay_runtime_python(instance.state_dir) if instance.follows_served_release else Path(os.sys.executable)
    node(action, "Command", str(python))
    node(action, "Arguments", subprocess.list2cmdline(["-I", str(instance.state_dir / "task-runner.py")]))
    node(action, "WorkingDirectory", str(instance.state_dir))
    return ET.tostring(root, encoding="unicode")


def _current(observed: str, expected: str) -> bool:
    try:
        actual = ET.fromstring(observed)
        desired = ET.fromstring(expected)
        def matches(want, have):
            if have is None or want.attrib != {k: have.attrib.get(k) for k in want.attrib}:
                return False
            if (want.text or "").strip() != (have.text or "").strip():
                return False
            return all(matches(child, have.find(child.tag)) for child in want)
        return matches(desired, actual)
    except ET.ParseError:
        return False


def relay_task_status(*, instance=None, home=None, environ=None, runner= subprocess.run) -> RelayTaskStatus:
    selected = instance or resolve_relay_instance()
    present = current = loaded = False
    reason = ""
    available = True
    try:
        sid = _user(runner)
        # Query the scheduler itself first: a failed task query must not hide a
        # policy/service restriction as an absent task.
        _checked(["schtasks", "/Query", "/FO", "CSV", "/NH"], runner)
        result = _run(["schtasks", "/Query", "/TN", selected.label, "/XML"], runner)
        present = result.returncode == 0
        if present:
            current = _current(result.stdout, relay_task_document(selected, user_sid=sid))
            name = selected.label.replace("'", "''")
            state = _checked([
                "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                "$s=New-Object -ComObject Schedule.Service; $s.Connect(); "
                f"[int]$s.GetFolder('\\').GetTask('{name}').State",
            ], runner)
            loaded = state == "4"
            if state == "1":
                reason = "relay_task_disabled: enable the task with `yoke relay install`"
        if present and not current:
            reason = "relay_task_outdated: retry `yoke relay install` to restore the task settings"
    except RelayInstallError as exc:
        available = False
        reason = str(exc)
    return RelayTaskStatus(available, present, current, loaded, selected.label,
                           selected.environment, selected.state_dir, reason)


def install_relay_task(*, instance=None, home=None, environ: Mapping[str, str] | None = None,
                       runner= subprocess.run, pin_release=relay_install.pin_relay_release):
    selected = instance or resolve_relay_instance()
    if refusal := door_relay_refusal(selected):
        raise RelayInstallError(refusal, code=USE_HTTPS_ENV)
    sid = _user(runner)
    _checked(["schtasks", "/Query", "/FO", "CSV", "/NH"], runner)
    try:
        launcher = relay_install.converge_relay_launcher(selected, pin_release=pin_release)
    except RelayReleaseError as exc:
        raise RelayInstallError(str(exc), code=exc.code) from exc
    create_private_directory(selected.state_dir)
    source_env = os.environ if environ is None else environ
    environment = {
        machine_paths.CONFIG_FILE_ENV: str(selected.config_path),
        machine_paths.HOME_ENV: str(selected.yoke_home),
        "PATH": source_env.get("PATH", ""),
    }
    if selected.follows_served_release:
        argv = [str(relay_runtime_python(selected.state_dir)), "-I",
                str(launcher.with_suffix(".py")), "--env", selected.environment, "relay", "serve"]
    else:
        argv = [str(launcher), "--env", selected.environment, "relay", "serve"]
    body = ("import os, subprocess\n"
            f"os.environ.update({environment!r})\n"
            f"with open({str(selected.stdout_log)!r}, 'ab', buffering=0) as out, "
            f"open({str(selected.stderr_log)!r}, 'ab', buffering=0) as err:\n"
            f"    raise SystemExit(subprocess.call({argv!r}, stdout=out, stderr=err))\n")
    write_owner_private(selected.state_dir / "task-runner.py", body)
    path = selected.state_dir / "task.xml"
    write_owner_private(path, relay_task_document(selected, user_sid=sid).encode("utf-16"))
    _checked(["schtasks", "/Create", "/TN", selected.label, "/XML", str(path), "/F"], runner)
    _checked(["schtasks", "/Run", "/TN", selected.label], runner)
    status = relay_task_status(instance=selected, runner=runner)
    deadline = time.monotonic() + 5
    while status.task_current and not status.reason and not status.loaded and time.monotonic() < deadline:
        time.sleep(0.1)
        status = relay_task_status(instance=selected, runner=runner)
    if status.reason or not (status.task_current and status.loaded):
        raise _unavailable(status.reason or "the task did not enter the running state; inspect its history")
    return status


def uninstall_relay_task(*, instance=None, home=None, runner= subprocess.run):
    selected = instance or resolve_relay_instance()
    status = relay_task_status(instance=selected, runner=runner)
    if not status.supported:
        raise _unavailable(status.reason)
    if status.task_present:
        if status.loaded:
            _checked(["schtasks", "/End", "/TN", selected.label], runner)
        _checked(["schtasks", "/Delete", "/TN", selected.label, "/F"], runner)
    status = relay_task_status(instance=selected, runner=runner)
    if status.reason or status.task_present:
        raise _unavailable(status.reason or "the task remains installed; retry relay uninstall")
    for name in ("task-runner.py", "task.xml"):
        (selected.state_dir / name).unlink(missing_ok=True)
    return status
