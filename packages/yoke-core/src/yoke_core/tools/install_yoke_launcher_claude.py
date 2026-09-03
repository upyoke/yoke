"""Claude.app preference helper for ``install_yoke_launcher``."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from yoke_contracts.harness_unattended_posture import (
    CLAUDE_BYPASS_KEY,
    CLAUDE_PERMISSIONS_CONTAINER,
    claude_config_path as _claude_config_path,
    claude_settings_path,
    claude_settings_problems,
)
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_SETTINGS_PERMISSION_MODE,
    CLAUDE_SETTINGS_PERMISSION_MODE_KEY,
)


CLAUDE_APP_CONFIG_PATH = _claude_config_path()


def configure_claude_app_bypass_permissions(
    *,
    config_path: Optional[Path] = None,
    stream=None,
) -> bool:
    """Set ``bypassPermissionsModeEnabled=true`` in Claude.app prefs.

    The patch is macOS-only, conservative, and respects explicit ``False``.
    It only writes when the key is absent.
    """
    if sys.platform != "darwin":
        return False
    target = config_path if config_path is not None else CLAUDE_APP_CONFIG_PATH
    if not target.is_file():
        return False
    out = stream if stream is not None else sys.stdout
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out.write(
            f"Could not parse Claude.app config at {target}: {exc}\n"
            f"Skipping bypass-permissions patch.\n"
        )
        return False
    if not isinstance(data, dict):
        return False
    prefs = data.setdefault("preferences", {})
    if not isinstance(prefs, dict):
        return False
    current = prefs.get(CLAUDE_BYPASS_KEY)
    if current is True:
        return False
    if current is False:
        return False
    prefs[CLAUDE_BYPASS_KEY] = True
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError as exc:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        out.write(f"Could not write Claude.app config at {target}: {exc}\n")
        return False
    out.write(
        f"Enabled Claude.app {CLAUDE_BYPASS_KEY} in {target}.\n"
        f"Quit and relaunch Claude.app to pick up the change.\n"
        f"(Pass --skip-harness-permissions on future runs to opt out.)\n\n"
    )
    return True


def configure_claude_cli_permission_mode(
    *,
    settings_path: Optional[Path] = None,
    stream=None,
) -> list:
    """Set the Claude CLI's own default permission mode; report what it did.

    The desktop app's preference above governs the app; the CLI reads this
    file, so a machine with only one of them still prompts on the other
    surface. Seeded only when the mode is absent — a mode the operator chose
    is reported and left alone.
    """
    target = settings_path if settings_path is not None else claude_settings_path()
    if not target.parent.is_dir():
        return []
    out = stream if stream is not None else sys.stdout
    try:
        data = json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
    except (OSError, json.JSONDecodeError) as exc:
        return [f"claude-code: {target} could not be read ({exc})"]
    if not isinstance(data, dict):
        return [f"claude-code: {target} is not a JSON object"]
    permissions = data.get(CLAUDE_PERMISSIONS_CONTAINER)
    permissions = permissions if isinstance(permissions, dict) else {}
    current = permissions.get(CLAUDE_SETTINGS_PERMISSION_MODE_KEY)
    if current == CLAUDE_SETTINGS_PERMISSION_MODE:
        return []
    if current is not None:
        return [
            f"claude-code: left your own setting in place — "
            f"{claude_settings_problems(data)[0]}; the CLI will keep asking "
            "until you change it"
        ]
    permissions[CLAUDE_SETTINGS_PERMISSION_MODE_KEY] = CLAUDE_SETTINGS_PERMISSION_MODE
    data[CLAUDE_PERMISSIONS_CONTAINER] = permissions
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError as exc:
        out.write(f"Could not write Claude CLI settings at {target}: {exc}\n")
        return [f"claude-code: {target} could not be updated ({exc})"]
    return [
        f"claude-code: enabled unattended mode in {target} "
        f"({CLAUDE_PERMISSIONS_CONTAINER}."
        f"{CLAUDE_SETTINGS_PERMISSION_MODE_KEY})"
    ]
