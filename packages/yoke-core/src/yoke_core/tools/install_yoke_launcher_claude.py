"""Claude.app preference helper for ``install_yoke_launcher``."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional


CLAUDE_APP_CONFIG_PATH = (
    Path("~/Library/Application Support/Claude/claude_desktop_config.json").expanduser()
)


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
    current = prefs.get("bypassPermissionsModeEnabled")
    if current is True:
        return False
    if current is False:
        return False
    prefs["bypassPermissionsModeEnabled"] = True
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
        f"Enabled Claude.app bypassPermissionsModeEnabled in {target}.\n"
        f"Quit and relaunch Claude.app to pick up the change.\n"
        f"(Pass --skip-claude-config on future runs to opt out.)\n\n"
    )
    return True
