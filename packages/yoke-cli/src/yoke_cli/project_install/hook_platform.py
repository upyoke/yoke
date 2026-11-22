"""Render server-provided hook commands for the installing machine's OS.

The server sends POSIX commands only; this client composes every Windows
form, so an older client keeps writing the form its own ``yoke hook
evaluate`` can parse.
"""

from copy import deepcopy
import os
import re

from yoke_contracts.hook_runner.config_owner import (
    CLAUDE_CONFIG_OWNER,
    CURSOR_PROJECT_CONFIG_OWNER,
)
from yoke_contracts.hook_shell_command import windows_hook_command
from yoke_contracts.machine_hooks_render import YOKE_HOOK_EVALUATE

_VERB = re.compile(rf"{re.escape(YOKE_HOOK_EVALUATE)} (\w+)")


def native_bundle_hooks(bundle: dict) -> dict:
    """Keep server event/matcher policy while selecting local command syntax.

    Codex carries its Windows command beside the POSIX one on every host;
    Claude and Cursor hold one command, in the installing host's form.
    """
    result = deepcopy(bundle)
    for key, harness, owner in (
        ("claude_settings_hooks", "claude-code", CLAUDE_CONFIG_OWNER),
        ("codex_hooks", "codex", None),
        ("cursor_hooks", "cursor", CURSOR_PROJECT_CONFIG_OWNER),
    ):
        if harness != "codex" and os.name != "nt":
            continue
        for entries in result.get("hooks", {}).get(key, {}).values():
            for entry in entries:
                for handler in entry.get("hooks", [entry]):
                    verb = _VERB.search(handler.get("command", ""))
                    if verb is None:
                        continue
                    command = windows_hook_command(harness, verb.group(1), owner)
                    handler["commandWindows" if harness == "codex" else "command"] = (
                        command
                    )
    return result
