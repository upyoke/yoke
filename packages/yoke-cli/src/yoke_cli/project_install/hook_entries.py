"""Schema-neutral identities for installed project hook entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_cli.project_install.hook_schema import (
    HOOK_FORMAT_CURSOR,
    HOOK_FORMAT_NESTED,
)


CURSOR_HOOKS_REL = ".cursor/hooks.json"


def hook_entry_format(settings_rel: str | Path) -> str:
    """Return the hook entry schema used by one settings file."""
    normalized = str(settings_rel).replace("\\", "/")
    return (
        HOOK_FORMAT_CURSOR
        if normalized.endswith(CURSOR_HOOKS_REL)
        else HOOK_FORMAT_NESTED
    )


def entry_key(entry: Dict[str, Any]) -> Tuple[Any, Tuple[str, ...], Any]:
    """Return matcher, commands, and Cursor timeout identity."""
    if "hooks" not in entry and isinstance(entry.get("command"), str):
        return (entry.get("matcher"), (entry["command"],), entry.get("timeout"))
    commands = tuple(
        str(hook.get("command") or "")
        for hook in entry.get("hooks") or []
        if isinstance(hook, dict)
    )
    return (entry.get("matcher"), commands, None)


def record(event: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return the manifest identity record for one hook entry."""
    matcher, commands, timeout = entry_key(entry)
    result = {"event": event, "matcher": matcher, "commands": list(commands)}
    if "hooks" not in entry and isinstance(entry.get("command"), str):
        result["timeout"] = timeout
    return result


def record_key(value: Dict[str, Any]) -> Tuple[str, Any, Tuple[str, ...], Any]:
    """Return the comparison key for one manifest identity record."""
    return (
        str(value.get("event") or ""),
        value.get("matcher"),
        tuple(value.get("commands") or ()),
        value.get("timeout"),
    )


def provided_records(hooks_subtree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return manifest records for every bundle-provided hook entry."""
    records: List[Dict[str, Any]] = []
    for event in sorted(hooks_subtree):
        for entry in hooks_subtree[event] or []:
            records.append(record(event, entry))
    return records


__all__ = [
    "CURSOR_HOOKS_REL",
    "entry_key",
    "hook_entry_format",
    "provided_records",
    "record",
    "record_key",
]
