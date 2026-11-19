"""Find and reclaim Yoke-owned per-environment Windows and Linux relay jobs."""

from __future__ import annotations

import csv
from pathlib import Path
import shlex
import stat
import subprocess
import xml.etree.ElementTree as ET

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV
from yoke_contracts.machine_config.relay_instance import RELAY_LABEL_PREFIX
from yoke_core.domain import relay_systemd_status as systemd
from yoke_core.tools import session_relay_task_pins as task_pins
from yoke_core.tools import session_relay_task_scheduler as scheduler


def _orphan(label: str, config: str, argv: list[str]) -> bool:
    task_pins.pinned_environment(label, config, argv)
    try:
        return not stat.S_ISREG(Path(config).stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return True


def _systemd_pins(unit: Path) -> tuple[str, list[str]]:
    if unit.is_symlink():
        raise ValueError("unit is a symbolic link")
    section = ""
    config = ""
    argv = []
    for line in unit.read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            section = line
        if section != "[Service]":
            continue
        if line.startswith("Environment="):
            for assignment in shlex.split(line.removeprefix("Environment=")):
                key, _, value = assignment.partition("=")
                if key == CONFIG_FILE_ENV:
                    config = value.replace("%%", "%")
        if line.startswith("ExecStart="):
            argv = [part.replace("%%", "%").replace("$$", "$")
                    for part in shlex.split(line.removeprefix("ExecStart="))]
    return config, argv


def scan_systemd(directory: Path) -> tuple[list[Path], list[str]]:
    orphans = []
    unreadable = []
    for unit in sorted(directory.glob(f"{RELAY_LABEL_PREFIX}*.service")):
        if not task_pins.instance_name(unit.stem):
            continue
        try:
            if _orphan(unit.stem, *_systemd_pins(unit)):
                orphans.append(unit)
        except (OSError, ValueError) as exc:
            unreadable.append(f"{unit.name}: {exc}")
    return orphans, unreadable


def reclaim_systemd(unit: Path, *, runner=subprocess.run) -> bool:
    # Re-check the pin immediately before removing a job.
    if not unit.exists() or not _orphan(unit.stem, *_systemd_pins(unit)):
        return False
    systemd._checked(["systemctl", "--user", "disable", "--now", unit.name], runner)
    unit.unlink(missing_ok=True)
    systemd._checked(["systemctl", "--user", "daemon-reload"], runner)
    return True


def _orphan_task(label: str, account: tuple[str, str], runner) -> bool:
    raw = scheduler._checked(["schtasks", "/Query", "/TN", label, "/XML"], runner)
    document = ET.fromstring(raw)
    if not task_pins.runs_as(document, account):
        return False
    pins = task_pins.task_pins(document, label)
    return _orphan(label, pins.config, pins.argv)


def scan_tasks(*, runner=subprocess.run) -> tuple[list[str], list[str]]:
    account = scheduler._account(runner)
    listing = scheduler._checked(["schtasks", "/Query", "/FO", "CSV", "/NH"], runner)
    labels = {row[0].removeprefix("\\") for row in csv.reader(listing.splitlines()) if row}
    orphans = []
    unreadable = []
    for label in sorted(filter(task_pins.instance_name, labels)):
        try:
            if _orphan_task(label, account, runner):
                orphans.append(label)
        except (scheduler.RelayInstallError, OSError, ValueError, SyntaxError, ET.ParseError) as exc:
            unreadable.append(f"{label}: {exc}")
    return orphans, unreadable


def reclaim_task(label: str, *, runner=subprocess.run) -> bool:
    if not _orphan_task(label, scheduler._account(runner), runner):
        return False
    if scheduler.relay_task_state(label, runner) == "4":
        scheduler._checked(["schtasks", "/End", "/TN", label], runner)
    scheduler._checked(["schtasks", "/Delete", "/TN", label, "/F"], runner)
    return True
