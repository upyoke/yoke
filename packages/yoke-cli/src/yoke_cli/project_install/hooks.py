"""Hook config merge/de-merge for ``yoke install`` / ``uninstall``.

Merges the bundle's ``claude_settings_hooks`` / ``codex_hooks`` subtrees
into a project repo's ``.claude/settings.json`` and ``.codex/hooks.json``
without disturbing operator-authored entries, and removes exactly the
bundle-provided entries on uninstall.

Identity of a hook entry is ``(matcher, command strings)`` within its
event — matching on the command string alone would collapse Yoke's
per-matcher entries (every ``PreToolUse`` matcher shares one command).
Claude's hook schema is all-or-nothing, so entries are appended in the
exact nested ``{matcher?, hooks: [{type, command}]}`` shape the bundle
carries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_cli.project_install.files import ProjectInstallError

CLAUDE_SETTINGS_REL = ".claude/settings.json"
CODEX_HOOKS_REL = ".codex/hooks.json"

# Bundle hooks key -> project settings file carrying that subtree.
SETTINGS_FILE_BY_HOOKS_KEY = {
    "claude_settings_hooks": CLAUDE_SETTINGS_REL,
    "codex_hooks": CODEX_HOOKS_REL,
}


def _entry_key(entry: Dict[str, Any]) -> Tuple[Any, Tuple[str, ...]]:
    commands = tuple(
        str(hook.get("command") or "")
        for hook in entry.get("hooks") or []
        if isinstance(hook, dict)
    )
    return (entry.get("matcher"), commands)


def _record(event: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    matcher, commands = _entry_key(entry)
    return {"event": event, "matcher": matcher, "commands": list(commands)}


def record_key(record: Dict[str, Any]) -> Tuple[str, Any, Tuple[str, ...]]:
    return (
        str(record.get("event") or ""),
        record.get("matcher"),
        tuple(record.get("commands") or ()),
    )


def provided_records(hooks_subtree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Flat ``{event, matcher, commands}`` records for every bundle entry."""
    records: List[Dict[str, Any]] = []
    for event in sorted(hooks_subtree):
        for entry in hooks_subtree[event] or []:
            records.append(_record(event, entry))
    return records


def _load_settings(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            f"{path} is not valid JSON ({exc}); repair it before rerunning "
            "`yoke project install`"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError(f"{path} must contain a JSON object")
    return payload


def _write_settings(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def merge_hooks_file(
    repo_root: Path, settings_rel: str, hooks_subtree: Dict[str, Any]
) -> Dict[str, Any]:
    """Ensure every bundle hook entry exists in the project settings file.

    Returns ``{"created": bool, "added": [records]}``. Operator-authored
    entries are never removed or reordered; missing bundle entries append
    at the end of their event's array.
    """
    target = repo_root / settings_rel
    if not target.is_file():
        _write_settings(target, {"hooks": hooks_subtree})
        return {
            "created": True,
            "added": provided_records(hooks_subtree),
        }
    payload = _load_settings(target)
    hooks = payload.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ProjectInstallError(
            f"{target} has a non-object 'hooks' key; repair it before "
            "rerunning `yoke project install`"
        )
    added: List[Dict[str, Any]] = []
    for event in sorted(hooks_subtree):
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            raise ProjectInstallError(
                f"{target} hooks.{event} must be an array; repair it before "
                "rerunning `yoke project install`"
            )
        existing = {_entry_key(e) for e in entries if isinstance(e, dict)}
        for entry in hooks_subtree[event] or []:
            if _entry_key(entry) in existing:
                continue
            entries.append(entry)
            added.append(_record(event, entry))
    if added:
        _write_settings(target, payload)
    return {"created": False, "added": added}


def demerge_hooks_file(
    repo_root: Path,
    settings_rel: str,
    records: List[Dict[str, Any]],
    *,
    created_by_install: bool,
) -> Dict[str, Any]:
    """Remove exactly the recorded bundle entries from the settings file.

    Returns ``{"removed": [records], "deleted_file": bool}``. The file is
    deleted only when it becomes ``{"hooks": {}}``-empty AND install
    created it; operator-authored files and entries always survive.
    """
    target = repo_root / settings_rel
    if not target.is_file():
        return {"removed": [], "deleted_file": False}
    payload = _load_settings(target)
    hooks = payload.get("hooks")
    if not isinstance(hooks, dict):
        return {"removed": [], "deleted_file": False}
    record_keys = {record_key(r) for r in records}
    removed: List[Dict[str, Any]] = []
    for event in list(hooks):
        entries = hooks.get(event)
        if not isinstance(entries, list):
            continue
        kept: List[Any] = []
        for entry in entries:
            if (
                isinstance(entry, dict)
                and (event, *_entry_key(entry)) in record_keys
            ):
                removed.append(_record(event, entry))
                continue
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]  # event held only Yoke entries
    if not removed:
        return {"removed": [], "deleted_file": False}
    if created_by_install and payload == {"hooks": {}}:
        target.unlink()
        from yoke_cli.project_install.files import remove_empty_parents

        remove_empty_parents(repo_root, settings_rel)
        return {"removed": removed, "deleted_file": True}
    _write_settings(target, payload)
    return {"removed": removed, "deleted_file": False}


__all__ = [
    "CLAUDE_SETTINGS_REL",
    "CODEX_HOOKS_REL",
    "SETTINGS_FILE_BY_HOOKS_KEY",
    "demerge_hooks_file",
    "merge_hooks_file",
    "provided_records",
    "record_key",
]
