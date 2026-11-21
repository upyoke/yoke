"""Schema-neutral identities for installed project hook entries."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_contracts.project_contract.hook_schema import HOOK_FORMAT_CURSOR, HOOK_FORMAT_NESTED
from yoke_contracts.hook_runner.config_owner import CONFIG_OWNER_ENV_VAR
from yoke_contracts.hook_shell_command import hook_command_source
from yoke_contracts.machine_hooks_render import YOKE_HOOK_EVALUATE

_EVALUATE = re.compile(rf"{re.escape(YOKE_HOOK_EVALUATE)} (\w+)")
_OWNER = re.compile(rf"{re.escape(CONFIG_OWNER_ENV_VAR)}=['\"]?([\w-]+)")


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
        command
        for hook in entry.get("hooks") or []
        if isinstance(hook, dict)
        for command in (
            [str(hook.get("command") or "")]
            + ([hook["commandWindows"]] if hook.get("commandWindows") else [])
        )
    )
    return (entry.get("matcher"), commands, None)


def _command_identity(command: str) -> Any:
    """One Yoke evaluate command's verb and owner, whatever its shell form."""
    source = hook_command_source(command)
    verb = _EVALUATE.search(source)
    if verb is None:
        return command
    owner = _OWNER.search(source)
    return (verb.group(1), owner.group(1) if owner else None)


def form_neutral_key(entry: Dict[str, Any]) -> Tuple[Any, Tuple[Any, ...], Any]:
    """Entry identity that matches one Yoke hook in its POSIX or Windows form.

    A file written on another host holds the same Yoke entry in the other
    shell form; matching it here keeps install from appending a duplicate.
    """
    matcher, commands, timeout = entry_key(entry)
    if "hooks" not in entry:
        return (matcher, tuple(_command_identity(c) for c in commands), timeout)
    primary = tuple(
        _command_identity(str(hook.get("command") or ""))
        for hook in entry.get("hooks") or []
        if isinstance(hook, dict)
    )
    return (matcher, primary, timeout)


def converge_event_entries(
    event: str,
    entries: List[Any],
    provided: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Make *entries* hold every provided entry; return (added, replaced).

    An existing entry with the same key but other content (such as an older
    handler ``timeout``), or that is the same Yoke hook in another shell form,
    is replaced in place by the provided entry; anything else missing appends.
    """
    provided_keys = {entry_key(entry) for entry in provided}
    added: List[Dict[str, Any]] = []
    replaced: List[Dict[str, Any]] = []
    for entry in provided:
        if entry in entries:
            continue
        key = entry_key(entry)
        index = next(
            (
                i
                for i, existing in enumerate(entries)
                if isinstance(existing, dict) and entry_key(existing) == key
            ),
            None,
        )
        if index is None:
            neutral = form_neutral_key(entry)
            index = next(
                (
                    i
                    for i, existing in enumerate(entries)
                    if isinstance(existing, dict)
                    and entry_key(existing) not in provided_keys
                    and form_neutral_key(existing) == neutral
                ),
                None,
            )
        if index is None:
            entries.append(entry)
        else:
            replaced.append(record(event, entries[index]))
            entries[index] = entry
        added.append(record(event, entry))
    return added, replaced


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
    "converge_event_entries",
    "entry_key",
    "form_neutral_key",
    "hook_entry_format",
    "provided_records",
    "record",
    "record_key",
]
