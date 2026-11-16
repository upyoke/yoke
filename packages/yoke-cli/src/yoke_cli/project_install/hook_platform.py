"""Render server-provided hook commands for the installing machine's OS."""

from copy import deepcopy
import os

from yoke_contracts.hook_runner.config_owner import (
    CLAUDE_CONFIG_OWNER,
    CURSOR_NATIVE_RUNNER_EVENTS,
    CURSOR_PROJECT_CONFIG_OWNER,
)
from yoke_contracts.hook_shell_command import windows_hook_command
from yoke_contracts.machine_hooks_render import YOKE_HOOK_EVALUATE


def native_bundle_hooks(bundle: dict) -> dict:
    """Keep server event/matcher policy while selecting local command syntax."""
    if os.name != "nt":
        return bundle
    result = deepcopy(bundle)
    for key, harness, owner in (
        ("claude_settings_hooks", "claude-code", CLAUDE_CONFIG_OWNER),
        ("codex_hooks", "codex", None),
        ("cursor_hooks", "cursor", CURSOR_PROJECT_CONFIG_OWNER),
    ):
        for event, entries in result.get("hooks", {}).get(key, {}).items():
            verb = (
                dict(CURSOR_NATIVE_RUNNER_EVENTS).get(event, event)
                if harness == "cursor"
                else event
            )
            for entry in entries:
                for handler in entry.get("hooks", [entry]):
                    if YOKE_HOOK_EVALUATE not in handler.get("command", ""):
                        continue
                    if harness == "codex" and handler.get("commandWindows"):
                        continue  # The server already rendered its event-to-verb mapping.
                    if harness == "codex" and verb == "PermissionRequest":
                        verb = "PreToolUse"
                    command = windows_hook_command(
                        harness,
                        verb,
                        owner,
                        resilient=harness == "cursor"
                        and verb in {"Stop", "SessionEnd"},
                    )
                    handler["commandWindows" if harness == "codex" else "command"] = (
                        command
                    )
    return result
