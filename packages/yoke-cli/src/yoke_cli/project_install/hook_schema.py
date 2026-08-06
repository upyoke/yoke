"""Validation for project hook configuration payloads."""

from __future__ import annotations

from typing import Any

from yoke_cli.project_install.files import ProjectInstallError

HOOK_FORMAT_CURSOR = "cursor"
HOOK_FORMAT_NESTED = "nested"


def validate_hooks_subtree(
    hooks_subtree: Any,
    *,
    label: str = "bundle hook subtree",
    entry_format: str = HOOK_FORMAT_NESTED,
) -> None:
    """Validate the command-hook shape before any checkout mutation."""
    if entry_format not in {HOOK_FORMAT_CURSOR, HOOK_FORMAT_NESTED}:
        raise ProjectInstallError(f"unknown hook entry format {entry_format!r}")
    if not isinstance(hooks_subtree, dict):
        raise ProjectInstallError(f"{label} must be an object")
    for event, entries in hooks_subtree.items():
        if not isinstance(event, str) or not event or not isinstance(entries, list):
            raise ProjectInstallError(
                f"{label} events must be non-empty strings containing arrays"
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise ProjectInstallError(
                    f"{label}.{event} contains a non-object hook entry"
                )
            matcher = entry.get("matcher")
            if entry_format == HOOK_FORMAT_CURSOR:
                timeout = entry.get("timeout")
                if (
                    (matcher is not None and not isinstance(matcher, str))
                    or not isinstance(entry.get("command"), str)
                    or not entry["command"]
                    or (
                        timeout is not None
                        and (
                            isinstance(timeout, bool)
                            or not isinstance(timeout, int)
                            or timeout <= 0
                        )
                    )
                ):
                    raise ProjectInstallError(
                        f"{label}.{event} contains an invalid Cursor hook entry"
                    )
                continue
            commands = entry.get("hooks")
            if (
                (matcher is not None and not isinstance(matcher, str))
                or not isinstance(commands, list)
                or not commands
            ):
                raise ProjectInstallError(
                    f"{label}.{event} contains an invalid matcher/hooks entry"
                )
            for command in commands:
                if (
                    not isinstance(command, dict)
                    or command.get("type") != "command"
                    or not isinstance(command.get("command"), str)
                    or not command["command"]
                ):
                    raise ProjectInstallError(
                        f"{label}.{event} contains an invalid command hook"
                    )


__all__ = [
    "HOOK_FORMAT_CURSOR",
    "HOOK_FORMAT_NESTED",
    "validate_hooks_subtree",
]
