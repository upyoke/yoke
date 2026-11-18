"""Find and reclaim Yoke-owned per-environment Windows and Linux relay jobs."""

from __future__ import annotations

import ast
import csv
from pathlib import Path
import re
import shlex
import stat
import subprocess
import xml.etree.ElementTree as ET

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV
from yoke_contracts.machine_config.relay_instance import (
    RELAY_LABEL_PREFIX,
    RELAY_STATE_ROOT_NAME,
    relay_instance_label,
)
from yoke_core.domain import relay_systemd_status as systemd
from yoke_core.tools import session_relay_task_scheduler as scheduler


def _instance_name(label: str) -> bool:
    return bool(label.startswith(RELAY_LABEL_PREFIX)
                and re.fullmatch(r"[0-9a-f]{16}", label.removeprefix(RELAY_LABEL_PREFIX)))


def _orphan(label: str, config: str, argv: list[str]) -> bool:
    path = Path(config)
    if (not path.is_absolute() or len(argv) < 5
            or argv[-4] != "--env" or argv[-2:] != ["relay", "serve"]
            or relay_instance_label(config_path=path, environment=argv[-3]) != label):
        raise ValueError("the service name does not match its pinned relay configuration")
    try:
        return not stat.S_ISREG(path.stat().st_mode)
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
        if not _instance_name(unit.stem):
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


def _task_pins(document: ET.Element, label: str) -> tuple[str, list[str]]:
    namespace = {"t": scheduler.TASK_NS}
    actions = document.findall("t:Actions/*", namespace)
    if len(actions) != 1 or actions[0].tag != f"{{{scheduler.TASK_NS}}}Exec":
        raise ValueError("task does not have a single relay runner")
    action = actions[0]
    state = Path(action.findtext("t:WorkingDirectory", "", namespace))
    path = state / "task-runner.py"
    if (not state.is_absolute()
            or Path(action.findtext("t:Command", "", namespace)) != scheduler.relay_runtime_python(state)
            or action.findtext("t:Arguments", "", namespace) != subprocess.list2cmdline(["-I", str(path)])):
        raise ValueError("task does not run the Yoke relay launcher")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Read the generated runner as data. Doctor never imports or executes it.
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    pins = next((ast.literal_eval(call.args[0]) for call in calls
                 if call.args and ast.unparse(call.func) == "os.environ.update"), {})
    argv = next((ast.literal_eval(call.args[0]) for call in calls
                 if call.args and ast.unparse(call.func) == "subprocess.call"), [])
    if not isinstance(pins, dict) or not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
        raise ValueError("relay runner has no literal configuration and command")
    home = pins.get(HOME_ENV)
    config = pins.get(CONFIG_FILE_ENV)
    if (not isinstance(home, str) or not isinstance(config, str)
            or state != Path(home) / RELAY_STATE_ROOT_NAME / label.removeprefix(RELAY_LABEL_PREFIX)):
        raise ValueError("task working directory does not match the relay runner")
    return config, argv


def _orphan_task(label: str, account: tuple[str, str], runner) -> bool:
    raw = scheduler._checked(["schtasks", "/Query", "/TN", label, "/XML"], runner)
    document = ET.fromstring(raw)
    namespace = {"t": scheduler.TASK_NS}
    principal = document.findtext("t:Principals/t:Principal/t:UserId", "", namespace)
    if principal.casefold() not in {value.casefold() for value in account}:
        return False
    return _orphan(label, *_task_pins(document, label))


def scan_tasks(*, runner=subprocess.run) -> tuple[list[str], list[str]]:
    account = scheduler._account(runner)
    listing = scheduler._checked(["schtasks", "/Query", "/FO", "CSV", "/NH"], runner)
    labels = {row[0].removeprefix("\\") for row in csv.reader(listing.splitlines()) if row}
    orphans = []
    unreadable = []
    for label in sorted(filter(_instance_name, labels)):
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
