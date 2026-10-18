"""Run exactly one Yoke hook when several configs fire the same event.

Two cases produce duplicates, and one rule-reading pass handles both before
any evaluation or server call:

* A machine-wide hook (owner ``<harness>-user``, from the harness's user
  config) steps aside when that harness's project config for the session
  folder holds a Yoke entry for the same native event. This holds for every
  harness and every event, tool events included. A project file "owns" an
  event through any ``yoke hook evaluate <Verb>`` command that is not itself
  a machine-wide entry, so older project renders without an owner marker
  still count.
* Cursor also imports Claude hook configs. An imported Claude hook steps
  aside on the events Cursor fires on both configs when Cursor's own project
  or user config owns the event. Tool-shaped events fire on the imported
  Claude config alone, so those never step aside.

A config the harness would reject does not own anything: skipping in its
favour would drop the only invocation the event produces.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.harness_machine_hooks import (
    HARNESS_BY_USER_OWNER,
    HARNESS_MACHINE_HOOKS,
    HarnessMachineHooks,
    entry_commands,
)
from yoke_contracts.hook_runner.config_owner import (
    CLAUDE_CONFIG_OWNER,
    CONFIG_OWNER_ENV_VAR,
    CURSOR_COMPATIBILITY_RUNNER_ALIASES,
    CURSOR_DUAL_CONFIG_RUNNER_EVENTS,
    CURSOR_EXECUTOR_ID,
    EXECUTOR_ENV_VAR,
    is_cursor_hook_payload,
    is_cursor_imported_claude_hook,
)

_USER_OWNER_PATTERN = re.compile(
    rf"(?<![\w-]){re.escape(CONFIG_OWNER_ENV_VAR)}="
    rf"(?:{'|'.join(re.escape(owner) for owner in HARNESS_BY_USER_OWNER)})(?![\w-])"
)
_FOLDER_ENV_VARS = ("CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR")


def _payload(stdin_data: str) -> dict[str, Any]:
    try:
        value = json.loads(stdin_data) if stdin_data else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _evaluate_pattern(verb: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w-])yoke\s+hook\s+evaluate\s+{re.escape(verb)}(?![\w-])")


def _hooks_block(path: Path, harness_id: str) -> Optional[dict[str, Any]]:
    """The file's hook map, or None when the harness would not load it."""
    from yoke_cli.filesystem_safety import first_symlink_component
    from yoke_cli.project_install.files import ProjectInstallError
    from yoke_cli.project_install.hook_schema import (
        HOOK_FORMAT_CURSOR,
        HOOK_FORMAT_NESTED,
        validate_hooks_subtree,
    )

    if harness_id == "cursor" and first_symlink_component(
        path.parent.parent, path, include_leaf=True
    ):
        return None  # Cursor refuses a hook config reached through a symlink.
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return None
        if harness_id == "cursor" and document.get("version") != 1:
            return None
        hooks = document.get("hooks")
        validate_hooks_subtree(
            hooks,
            label=f"{path} hooks",
            entry_format=HOOK_FORMAT_CURSOR if harness_id == "cursor" else HOOK_FORMAT_NESTED,
        )
    except (OSError, UnicodeError, ValueError, ProjectInstallError):
        return None
    return hooks if isinstance(hooks, dict) else None


def _config_owns(
    path: Path,
    spec: HarnessMachineHooks,
    verb: str,
    *,
    owner: Optional[str] = None,
) -> bool:
    """Whether *path* holds a Yoke entry for every native event of *verb*.

    With *owner*, the entry must carry that owner; without it, any Yoke entry
    that is not a machine-wide one counts.
    """
    native_events = spec.native_events_for(verb)
    hooks = _hooks_block(path, spec.harness_id) if native_events else None
    if hooks is None:
        return False
    evaluate = _evaluate_pattern(verb)
    marker = f"{CONFIG_OWNER_ENV_VAR}={owner}" if owner else ""

    def counts(command: str) -> bool:
        if not evaluate.search(command):
            return False
        return marker in command if marker else not _USER_OWNER_PATTERN.search(command)

    return all(
        any(counts(command) for entry in hooks.get(native, []) for command in entry_commands(entry))
        for native in native_events
    )


def _session_folder(environment: Mapping[str, str], payload: Mapping[str, Any]) -> Optional[Path]:
    candidates: list[object] = [environment.get(key) for key in _FOLDER_ENV_VARS]
    candidates.append(payload.get("cwd"))
    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots:
        candidates.append(roots[0])
    candidates.append(environment.get("YOKE_ROOT"))
    for value in candidates:
        if isinstance(value, str) and value:
            return Path(value)
    return None


def _search_dirs(spec: HarnessMachineHooks, folder: Path) -> list[Path]:
    if spec.project_config_search == "project_dir":
        return [folder]
    dirs: list[Path] = []
    for candidate in (folder, *folder.parents):
        dirs.append(candidate)
        if (candidate / ".git").exists():
            return dirs
    return [folder]


def project_config_owns(
    spec: HarnessMachineHooks, verb: str, folder: Optional[Path]
) -> bool:
    """Whether the harness's project config for *folder* owns *verb*."""
    if folder is None:
        return False
    return any(
        _config_owns(directory / relative, spec, verb)
        for directory in _search_dirs(spec, folder)
        for relative in spec.project_configs
    )


def _cursor_owns(verb: str, environment: Mapping[str, str], folder: Optional[Path]) -> bool:
    cursor = HARNESS_MACHINE_HOOKS["cursor"]
    if project_config_owns(cursor, verb, folder):
        return True
    return _config_owns(
        cursor.user_config_path(environment), cursor, verb, owner=cursor.config_owner
    )


def should_skip_config_duplicate(
    event_name: str,
    environment: Mapping[str, str],
    stdin_data: str,
) -> bool:
    """Return whether another config owns this invocation of *event_name*."""
    payload = _payload(stdin_data)
    verb = CURSOR_COMPATIBILITY_RUNNER_ALIASES.get(event_name, event_name)
    folder = _session_folder(environment, payload)
    under_cursor = is_cursor_hook_payload(environment, payload)
    owner = environment.get(CONFIG_OWNER_ENV_VAR, "")
    harness_id = HARNESS_BY_USER_OWNER.get(owner)
    if harness_id is not None:
        if project_config_owns(HARNESS_MACHINE_HOOKS[harness_id], verb, folder):
            return True
        # Cursor also fires an imported user-level Claude config.
        return (
            harness_id == "claude-code"
            and under_cursor
            and verb in CURSOR_DUAL_CONFIG_RUNNER_EVENTS
            and _cursor_owns(verb, environment, folder)
        )
    if owner == CLAUDE_CONFIG_OWNER and is_cursor_imported_claude_hook(environment, payload):
        return verb in CURSOR_DUAL_CONFIG_RUNNER_EVENTS and _cursor_owns(
            verb, environment, folder
        )
    return False


def is_cursor_config_invocation(
    environment: Mapping[str, str],
    stdin_data: str,
) -> bool:
    """Return whether process plus payload prove a Cursor config hook."""
    return environment.get(
        EXECUTOR_ENV_VAR
    ) == CURSOR_EXECUTOR_ID or is_cursor_hook_payload(environment, _payload(stdin_data))


__all__ = [
    "is_cursor_config_invocation",
    "project_config_owns",
    "should_skip_config_duplicate",
]
