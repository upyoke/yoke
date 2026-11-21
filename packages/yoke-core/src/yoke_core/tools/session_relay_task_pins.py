"""Read a Windows relay task's pinned runner as data, never by running it.

Doctor's orphan scan and machine uninstall both prove a scheduled task is a
Yoke relay from its exported XML and the generated ``task-runner.py``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import xml.etree.ElementTree as ET

from yoke_contracts.machine_config.paths import CONFIG_FILE_ENV, HOME_ENV
from yoke_contracts.machine_config.relay_instance import (
    RELAY_LABEL_PREFIX,
    RELAY_STATE_ROOT_NAME,
    relay_instance_label,
)
from yoke_core.tools import session_relay_task_scheduler as scheduler


@dataclass(frozen=True)
class TaskPins:
    state_dir: Path
    config: str
    argv: list[str]


def instance_name(label: str) -> bool:
    return bool(label.startswith(RELAY_LABEL_PREFIX)
                and re.fullmatch(r"[0-9a-f]{16}", label.removeprefix(RELAY_LABEL_PREFIX)))


def runs_as(document: ET.Element, account: tuple[str, str]) -> bool:
    """Whether the task's principal is this user, by SID or account name."""
    namespace = {"t": scheduler.TASK_NS}
    principal = document.findtext("t:Principals/t:Principal/t:UserId", "", namespace)
    return principal.casefold() in {value.casefold() for value in account}


def pinned_environment(label: str, config: str, argv: list[str]) -> str:
    """The relay environment the runner serves, proven against the task name."""
    path = Path(config)
    if (not path.is_absolute() or len(argv) < 5
            or argv[-4] != "--env" or argv[-2:] != ["relay", "serve"]
            or relay_instance_label(config_path=path, environment=argv[-3]) != label):
        raise ValueError("the service name does not match its pinned relay configuration")
    return argv[-3]


def task_pins(document: ET.Element, label: str) -> TaskPins:
    namespace = {"t": scheduler.TASK_NS}
    actions = document.findall("t:Actions/*", namespace)
    if len(actions) != 1 or actions[0].tag != f"{{{scheduler.TASK_NS}}}Exec":
        raise ValueError("task does not have a single relay runner")
    action = actions[0]
    state = Path(action.findtext("t:WorkingDirectory", "", namespace))
    path = state / "task-runner.py"
    digest = label.removeprefix(RELAY_LABEL_PREFIX)
    if (not state.is_absolute()
            or state.name != digest or state.parent.name != RELAY_STATE_ROOT_NAME
            or Path(action.findtext("t:Command", "", namespace)) != scheduler.relay_task_command(state)
            or action.findtext("t:Arguments", "", namespace) != subprocess.list2cmdline(["-I", str(path)])
            or path.is_symlink()):
        raise ValueError("task does not run the Yoke relay launcher")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # Read the generated runner as data. Nothing imports or executes it.
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
            or state != Path(home) / RELAY_STATE_ROOT_NAME / digest):
        raise ValueError("task working directory does not match the relay runner")
    return TaskPins(state, config, argv)
