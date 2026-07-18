"""Validation for project hook configuration payloads."""

from __future__ import annotations

from typing import Any

from yoke_cli.project_install.files import ProjectInstallError


def validate_hooks_subtree(
    hooks_subtree: Any,
    *,
    label: str = "bundle hook subtree",
) -> None:
    """Validate the command-hook shape before any checkout mutation."""
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


__all__ = ["validate_hooks_subtree"]
