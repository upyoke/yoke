"""Deduplicate hook configs that Cursor loads from multiple owners."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yoke_contracts.hook_runner.config_owner import (
    CONFIG_OWNER_ENV_VAR,
    CURSOR_COMPATIBILITY_RUNNER_ALIASES,
    CURSOR_EXECUTOR_ID,
    CURSOR_LIFECYCLE_COMMAND_MARKERS,
    CURSOR_NATIVE_RUNNER_EVENTS,
    CURSOR_PROJECT_CONFIG_OWNER,
    CURSOR_USER_LIFECYCLE_OWNER,
    EXECUTOR_ENV_VAR,
    is_cursor_hook_payload,
    is_cursor_imported_claude_hook,
)
from yoke_cli.filesystem_safety import first_symlink_component
from yoke_cli.project_install.files import ProjectInstallError
from yoke_cli.project_install.hook_schema import (
    HOOK_FORMAT_CURSOR,
    validate_hooks_subtree,
)


_CURSOR_EVENTS_BY_RUNNER_EVENT = {
    runner_event: tuple(
        native_event
        for native_event, candidate in CURSOR_NATIVE_RUNNER_EVENTS
        if candidate == runner_event
    )
    for runner_event in {
        candidate for _, candidate in CURSOR_NATIVE_RUNNER_EVENTS
    }
}


def _payload(stdin_data: str) -> dict[str, Any]:
    try:
        value = json.loads(stdin_data) if stdin_data else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _cursor_config_owns_event(
    root: Path,
    event_name: str,
    owner: str,
    *,
    accepted_markers: tuple[str, ...] = (),
) -> bool:
    native_verb = CURSOR_COMPATIBILITY_RUNNER_ALIASES.get(
        event_name, event_name,
    )
    native_events = _CURSOR_EVENTS_BY_RUNNER_EVENT.get(native_verb)
    if not native_events:
        return False
    relative = Path(".cursor/hooks.json")
    config_path = root / relative
    if (
        first_symlink_component(root, config_path, include_leaf=True)
        or not config_path.is_file()
    ):
        return False
    try:
        document = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != 1:
            return False
        hooks = document.get("hooks")
        validate_hooks_subtree(
            hooks,
            label=f"{config_path} hooks",
            entry_format=HOOK_FORMAT_CURSOR,
        )
        if not isinstance(hooks, dict):
            return False
    except (OSError, UnicodeError, ValueError, ProjectInstallError):
        return False
    owner_marker = f"{CONFIG_OWNER_ENV_VAR}={owner}"
    marker_pattern = re.compile(
        rf"(?<![\w=-]){re.escape(owner_marker)}(?![\w=-])"
    )
    evaluate_pattern = re.compile(
        rf"(?<![\w-])yoke\s+hook\s+evaluate\s+"
        rf"{re.escape(native_verb)}(?![\w-])"
    )
    return all(
        any(
            isinstance(entry, dict)
            and isinstance(entry.get("command"), str)
            and marker_pattern.search(entry["command"])
            and evaluate_pattern.search(entry["command"])
            and (
                not accepted_markers
                or any(marker in entry["command"] for marker in accepted_markers)
            )
            for entry in hooks.get(native_event, [])
        )
        for native_event in native_events
    )


def _project_cursor_config_owns_event(
    event_name: str,
    environment: Mapping[str, str],
    payload: Mapping[str, Any],
) -> bool:
    project_dir = environment.get("CURSOR_PROJECT_DIR") or payload.get("cwd")
    if not isinstance(project_dir, str) or not project_dir:
        return False
    return _cursor_config_owns_event(
        Path(project_dir), event_name, CURSOR_PROJECT_CONFIG_OWNER,
    )


def _user_cursor_config_owns_lifecycle_event(
    event_name: str, environment: Mapping[str, str],
) -> bool:
    if event_name not in {"Stop", "SessionEnd"}:
        return False
    home = environment.get("HOME")
    if not home:
        return False
    return _cursor_config_owns_event(
        Path(home),
        event_name,
        CURSOR_USER_LIFECYCLE_OWNER,
        accepted_markers=CURSOR_LIFECYCLE_COMMAND_MARKERS,
    )


def should_skip_config_duplicate(
    event_name: str,
    environment: Mapping[str, str],
    stdin_data: str,
) -> bool:
    """Return whether another active Cursor config owns this invocation."""
    payload = _payload(stdin_data)
    if is_cursor_imported_claude_hook(environment, payload):
        return (
            _project_cursor_config_owns_event(
                event_name, environment, payload,
            )
            or _user_cursor_config_owns_lifecycle_event(
                event_name, environment,
            )
        )
    return (
        environment.get(CONFIG_OWNER_ENV_VAR) == CURSOR_USER_LIFECYCLE_OWNER
        and is_cursor_hook_payload(environment, payload)
        and _project_cursor_config_owns_event(event_name, environment, payload)
    )


def is_cursor_config_invocation(
    environment: Mapping[str, str], stdin_data: str,
) -> bool:
    """Return whether process plus payload prove a Cursor config hook."""
    return (
        environment.get(EXECUTOR_ENV_VAR) == CURSOR_EXECUTOR_ID
        or is_cursor_hook_payload(environment, _payload(stdin_data))
    )


__all__ = ["is_cursor_config_invocation", "should_skip_config_duplicate"]
