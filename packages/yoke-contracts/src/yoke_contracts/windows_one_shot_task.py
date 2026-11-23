"""Run one command once in the signed-in desktop user's session.

A process under Windows Redirection Guard, as every OpenSSH session is, cannot
do some work its user's desktop can. An ``InteractiveToken`` task runs in that
desktop session without a stored password, and never starts when the user is
not signed in, so the signed-in check comes first and refuses at once.

The task has no trigger and no restart. A private directory holds its wrapper
and output log, and the task and directory are removed on every path.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Callable, Mapping, Sequence
import uuid
import xml.etree.ElementTree as ET

from yoke_contracts.designed_wait import announce_designed_wait
from yoke_contracts.owner_private_path import (
    create_owner_private_directory,
    write_owner_private,
)
from yoke_contracts.windows_task_scheduler import (
    Runner,
    SchedulerCommandError,
    TASK_NS,
    checked_output,
    current_account,
    run_command,
    task_node as node,
)

COMMAND_TIMEOUT_SECONDS = 30.0
POLL_SECONDS = 2.0
LOG_TAIL_CHARS = 2048
_STATE_QUEUED = 2
_STATE_RUNNING = 4
_RESULT_RUNNING = 0x41301
_RESULT_NOT_YET_RUN = 0x41303

_WRAPPER = """\
import json, os, subprocess, sys
spec = json.loads({spec!r})
with open(spec["log"], "wb") as log:
    try:
        code = subprocess.run(
            spec["argv"], stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, env={{**os.environ, **spec["environment"]}},
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).returncode
    except OSError as exc:
        log.write(f"could not start the command: {{exc}}".encode())
        code = 127
sys.exit(code)
"""


@dataclass(frozen=True)
class OneShotResult:
    exit_code: int
    log_tail: str


class OneShotRefused(RuntimeError):
    """The task could not start, finish or be removed; the text names why."""

    def __init__(self, reason: str, log_tail: str = "") -> None:
        super().__init__(reason)
        self.log_tail = log_tail


def task_document(
    *, user_sid: str, python: str, wrapper: Path, limit_seconds: int
) -> str:
    """Task XML: the desktop user's token, no trigger, no restart, one time limit."""
    root = ET.Element("Task", {"version": "1.2", "xmlns": TASK_NS})
    principal = node(node(root, "Principals"), "Principal", id="DesktopUser")
    node(principal, "UserId", user_sid)
    node(principal, "LogonType", "InteractiveToken")
    node(principal, "RunLevel", "LeastPrivilege")
    settings = node(root, "Settings")
    for name, value in {
        "MultipleInstancesPolicy": "IgnoreNew",
        "DisallowStartIfOnBatteries": "false",
        "StopIfGoingOnBatteries": "false",
        "AllowHardTerminate": "true",
        "Enabled": "true",
        "ExecutionTimeLimit": f"PT{limit_seconds}S",
    }.items():
        node(settings, name, value)
    action = node(node(root, "Actions", Context="DesktopUser"), "Exec")
    node(action, "Command", python)
    node(action, "Arguments", subprocess.list2cmdline(["-I", str(wrapper)]))
    node(action, "WorkingDirectory", str(wrapper.parent))
    return ET.tostring(root, encoding="unicode")


def user_has_desktop_session(account: str, runner: Runner) -> bool:
    """Whether ``query user`` lists this user.

    It exits 1 even when it lists a session, and its state column is
    localized, so only the row's user name decides. A disconnected session
    still counts: an interactive task can run in it.
    """
    result = run_command(
        ["query", "user"], runner, timeout=COMMAND_TIMEOUT_SECONDS
    )
    user = account.rsplit("\\", 1)[-1].casefold()
    return any(
        line.lstrip(" >").casefold().startswith(f"{user} ")
        for line in str(result.stdout).splitlines()
    )


def _task_status(name: str, runner: Runner) -> tuple[int, int]:
    output = checked_output(
        [
            "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$s=New-Object -ComObject Schedule.Service; $s.Connect(); "
            f"$t=$s.GetFolder('\\').GetTask('{name}'); "
            '"$([int]$t.State) $([int64]$t.LastTaskResult)"',
        ],
        runner,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    try:
        state, result = output.split()
        return int(state), int(result)
    except ValueError as exc:
        raise SchedulerCommandError(
            f"unreadable task status {output!r}"
        ) from exc


def _wait(
    name: str,
    limit_seconds: int,
    runner: Runner,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> int | None:
    """The task's exit code, or ``None`` when the time limit passes first."""
    announce_designed_wait(
        "scheduled install in the desktop session",
        max_wait_seconds=limit_seconds,
        cadence=f"every {POLL_SECONDS:g}s",
    )
    deadline = clock() + limit_seconds
    while True:
        state, result = _task_status(name, runner)
        active = state in {_STATE_QUEUED, _STATE_RUNNING}
        if not active and result not in {_RESULT_RUNNING, _RESULT_NOT_YET_RUN}:
            return result
        if clock() >= deadline:
            return None
        sleep(POLL_SECONDS)


def _tail(log: Path) -> str:
    """The log's end in ASCII: a refusal must print on any Windows console code page."""
    try:
        text = log.read_bytes()[-LOG_TAIL_CHARS:].decode("utf-8", "replace")
    except OSError:
        return ""
    return text.encode("ascii", "replace").decode("ascii").strip()


def _remove(
    name: str, work: Path, runner: Runner, *, created: bool, end: bool
) -> list[str]:
    """Remove the task and its files; name whatever remains."""
    problems: list[str] = []
    if created:
        commands = [["schtasks", "/Delete", "/TN", name, "/F"]]
        if end:
            commands.insert(0, ["schtasks", "/End", "/TN", name])
        for argv in commands:
            try:
                checked_output(argv, runner, timeout=COMMAND_TIMEOUT_SECONDS)
            except SchedulerCommandError as exc:
                problems.append(f"`{' '.join(argv)}` failed: {exc}")
    shutil.rmtree(work, ignore_errors=True)
    if work.exists():
        problems.append(f"could not remove {work}")
    return problems


def run_one_shot(
    argv: Sequence[str],
    *,
    python: str,
    environment: Mapping[str, str],
    limit_seconds: int,
    runner: Runner = subprocess.run,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> OneShotResult:
    """Run *argv* once as a desktop task; *limit_seconds* bounds task and wait.

    The task does not inherit this process's environment, so *environment*
    is written into its wrapper, inside the private directory.
    """
    try:
        sid, account = current_account(runner, timeout=COMMAND_TIMEOUT_SECONDS)
        signed_in = user_has_desktop_session(account, runner)
    except SchedulerCommandError as exc:
        raise OneShotRefused(f"Task Scheduler is unavailable: {exc}") from exc
    if not signed_in:
        raise OneShotRefused(f"{account} is not signed in at this machine's desktop")
    work = create_owner_private_directory(
        Path(tempfile.gettempdir()) / f"yoke-task-{uuid.uuid4().hex}"
    )
    name = f"Yoke-OneShot-{work.name}"
    log = work / "output.log"
    wrapper = work / "run.py"
    created = False
    exit_code: int | None = None
    failure = ""
    tail = ""
    try:
        try:
            spec = {"argv": list(argv), "environment": dict(environment), "log": str(log)}
            write_owner_private(wrapper, _WRAPPER.format(spec=json.dumps(spec)))
            document = work / "task.xml"
            write_owner_private(
                document,
                task_document(
                    user_sid=sid, python=python, wrapper=wrapper,
                    limit_seconds=limit_seconds,
                ).encode("utf-16"),
            )
            checked_output(
                ["schtasks", "/Create", "/TN", name, "/XML", str(document), "/F"],
                runner, timeout=COMMAND_TIMEOUT_SECONDS,
            )
            created = True
            checked_output(
                ["schtasks", "/Run", "/TN", name],
                runner, timeout=COMMAND_TIMEOUT_SECONDS,
            )
            exit_code = _wait(name, limit_seconds, runner, sleep, clock)
            if exit_code is None:
                failure = f"the task did not finish within {limit_seconds} seconds"
        except (SchedulerCommandError, OSError) as exc:
            failure = f"the task could not run: {exc}"
        tail = _tail(log)
    finally:
        problems = _remove(
            name, work, runner, created=created, end=exit_code is None
        )
    if failure:
        raise OneShotRefused("; ".join([failure, *problems]), tail)
    if problems:
        raise OneShotRefused(
            f"the task finished with exit {exit_code}, but cleanup failed: "
            + "; ".join(problems),
            tail,
        )
    return OneShotResult(int(exit_code), tail)


__all__ = ["OneShotRefused", "OneShotResult", "run_one_shot", "task_document"]
