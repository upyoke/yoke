"""The Windows Task Scheduler calls every scheduled Yoke task shares."""

from __future__ import annotations

import csv
import locale
import subprocess
from typing import Callable
import xml.etree.ElementTree as ET

Runner = Callable[..., subprocess.CompletedProcess[str]]
TASK_NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


class SchedulerCommandError(RuntimeError):
    """A scheduler command could not run or reported failure; the text says why."""


def _decode(value: object) -> object:
    if not isinstance(value, bytes):
        return value or ""
    if value.startswith((b"\xff\xfe", b"\xfe\xff")):
        return value.decode("utf-16")
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError:
        return value.decode(locale.getpreferredencoding(False), errors="replace")


def run_command(
    argv: list[str], runner: Runner, *, timeout: float
) -> subprocess.CompletedProcess[str]:
    """Run one scheduler command and decode its output, whatever its encoding."""
    try:
        result = runner(argv, check=False, capture_output=True, timeout=timeout)
        return subprocess.CompletedProcess(
            argv, result.returncode, _decode(result.stdout), _decode(result.stderr)
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise SchedulerCommandError(str(exc)) from exc


def checked_output(argv: list[str], runner: Runner, *, timeout: float) -> str:
    """The command's stripped stdout; a non-zero exit raises with its output."""
    result = run_command(argv, runner, timeout=timeout)
    if result.returncode:
        raise SchedulerCommandError(
            str(result.stderr or result.stdout or result.returncode).strip()
        )
    return result.stdout.strip()


def current_account(runner: Runner, *, timeout: float) -> tuple[str, str]:
    """The current user's SID and ``DOMAIN\\user`` name from one read.

    A task declares the SID, stable across renames; Task Scheduler may export
    the same account by name.
    """
    output = checked_output(
        ["whoami", "/user", "/fo", "csv", "/nh"], runner, timeout=timeout
    )
    rows = list(csv.reader(output.splitlines()))
    if not rows or len(rows[0]) != 2 or not rows[0][1].startswith("S-1-"):
        raise SchedulerCommandError("cannot resolve the current user's SID")
    return rows[0][1], rows[0][0]


def task_node(
    parent: ET.Element, name: str, text: str | None = None, **attributes: str
) -> ET.Element:
    """Append one task-XML element."""
    child = ET.SubElement(parent, name, attributes)
    child.text = text
    return child


__all__ = [
    "Runner",
    "SchedulerCommandError",
    "TASK_NS",
    "checked_output",
    "current_account",
    "run_command",
    "task_node",
]
