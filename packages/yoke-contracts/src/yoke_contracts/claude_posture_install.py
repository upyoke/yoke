"""Claude desktop preference helper for ``install_yoke_launcher``."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_unattended_posture import (
    CLAUDE_BYPASS_KEY,
    CLAUDE_PERMISSIONS_CONTAINER,
    claude_config_path,
    claude_settings_path,
)
from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_SETTINGS_PERMISSION_MODE,
    CLAUDE_SETTINGS_PERMISSION_MODE_KEY,
)


def configure_claude_app_bypass_permissions(
    *,
    config_path: Optional[Path] = None,
    stream=None,
) -> bool:
    """Set ``bypassPermissionsModeEnabled=true`` in Claude desktop prefs.

    Patch an existing platform config, including an explicit ``False``.
    """
    target = config_path if config_path is not None else claude_config_path()
    if not target.is_file():
        return False
    out = stream if stream is not None else sys.stdout
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        out.write(
            f"Could not parse Claude desktop config at {target}: {exc}\n"
            f"Skipping bypass-permissions patch.\n"
        )
        return False
    if not isinstance(data, dict):
        return False
    existing = ledger.existing_depth(data, ["preferences"])
    prefs = data.setdefault("preferences", {})
    if not isinstance(prefs, dict):
        return False
    had_current = CLAUDE_BYPASS_KEY in prefs
    current = prefs.get(CLAUDE_BYPASS_KEY)
    if current is True:
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
        out.write(f"Could not write Claude desktop config at {target}: {exc}\n")
        return False
    unrecorded = ledger.record(
        ledger.json_entry(
            target,
            ["preferences", CLAUDE_BYPASS_KEY],
            True,
            existing_depth=existing,
            **({"previous": current} if had_current else {}),
        )
    )
    if unrecorded:
        out.write(f"Claude desktop {CLAUDE_BYPASS_KEY}: {unrecorded}\n")
    out.write(
        f"Enabled Claude desktop {CLAUDE_BYPASS_KEY} in {target}.\n"
        f"Quit and relaunch Claude desktop to pick up the change.\n\n"
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
    surface. Both surfaces receive the unattended mode on every setup pass.
    """
    target = settings_path if settings_path is not None else claude_settings_path()
    if not target.parent.is_dir():
        return []
    out = stream if stream is not None else sys.stdout
    try:
        data = (
            json.loads(target.read_text(encoding="utf-8")) if target.is_file() else {}
        )
    except (OSError, json.JSONDecodeError) as exc:
        return [f"claude-code: {target} could not be read ({exc})"]
    if not isinstance(data, dict):
        return [f"claude-code: {target} is not a JSON object"]
    existing = ledger.existing_depth(data, [CLAUDE_PERMISSIONS_CONTAINER])
    permissions = data.get(CLAUDE_PERMISSIONS_CONTAINER)
    permissions = permissions if isinstance(permissions, dict) else {}
    had_current = CLAUDE_SETTINGS_PERMISSION_MODE_KEY in permissions
    current = permissions.get(CLAUDE_SETTINGS_PERMISSION_MODE_KEY)
    if current == CLAUDE_SETTINGS_PERMISSION_MODE:
        return []
    permissions[CLAUDE_SETTINGS_PERMISSION_MODE_KEY] = CLAUDE_SETTINGS_PERMISSION_MODE
    data[CLAUDE_PERMISSIONS_CONTAINER] = permissions
    tmp = target.with_suffix(target.suffix + ".yoke-tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(target))
    except OSError as exc:
        out.write(f"Could not write Claude CLI settings at {target}: {exc}\n")
        return [f"claude-code: {target} could not be updated ({exc})"]
    unrecorded = ledger.record(
        ledger.json_entry(
            target,
            [CLAUDE_PERMISSIONS_CONTAINER, CLAUDE_SETTINGS_PERMISSION_MODE_KEY],
            CLAUDE_SETTINGS_PERMISSION_MODE,
            existing_depth=existing,
            **({"previous": current} if had_current else {}),
        )
    )
    return [
        f"claude-code: enabled unattended mode in {target} "
        f"({CLAUDE_PERMISSIONS_CONTAINER}."
        f"{CLAUDE_SETTINGS_PERMISSION_MODE_KEY})",
        *([f"claude-code: {unrecorded}"] if unrecorded else []),
    ]
