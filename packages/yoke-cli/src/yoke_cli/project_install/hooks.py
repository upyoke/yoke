"""Hook config merge/de-merge for ``yoke install`` / ``uninstall``.

Merges the bundle's ``claude_settings_hooks`` / ``codex_hooks`` /
``cursor_hooks`` subtrees into a project repo's ``.claude/settings.json``,
``.codex/hooks.json``, and ``.cursor/hooks.json`` without disturbing
operator-authored entries, and removes exactly the bundle-provided entries
on uninstall.

Identity is matcher + command within its event, with timeout included for
Cursor. Claude and Codex carry nested ``hooks: [{type, command}]`` entries;
Cursor carries flat ``{command, timeout, matcher?}`` entries. Each settings
file is validated and reconciled in its native schema, so operator entries
remain in place while Yoke entries converge.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
)
from yoke_cli.project_install.hook_entries import (
    CURSOR_HOOKS_REL,
    entry_key as _entry_key,
    hook_entry_format,
    provided_records,
    record as _record,
    record_key,
)
from yoke_cli.project_install.hook_schema import validate_hooks_subtree

CLAUDE_SETTINGS_REL = ".claude/settings.json"
CODEX_HOOKS_REL = ".codex/hooks.json"

# Bundle hooks key -> project settings file carrying that subtree.
SETTINGS_FILE_BY_HOOKS_KEY = {
    "claude_settings_hooks": CLAUDE_SETTINGS_REL,
    "codex_hooks": CODEX_HOOKS_REL,
    "cursor_hooks": CURSOR_HOOKS_REL,
}

# Cursor validates its hooks file against a versioned schema and refuses to
# start when the file is invalid, so a freshly created .cursor/hooks.json
# seeds the version marker alongside the hooks map.
DEFAULT_PAYLOAD_BY_SETTINGS_REL = {
    CURSOR_HOOKS_REL: {"version": 1},
}


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
    if path.is_symlink():
        path.unlink()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _validated_settings_payload(path: Path) -> Dict[str, Any]:
    payload = _load_settings(path)
    hooks = payload.get("hooks", {})
    validate_hooks_subtree(
        hooks,
        label=f"{path} hooks",
        entry_format=hook_entry_format(path),
    )
    return payload


def _empty_payload(settings_rel: str) -> Dict[str, Any]:
    return {
        **(DEFAULT_PAYLOAD_BY_SETTINGS_REL.get(settings_rel) or {}),
        "hooks": {},
    }


def plan_hooks_file(
    repo_root: Path,
    settings_rel: str,
    hooks_subtree: Dict[str, Any],
    prior_records: List[Dict[str, Any]],
    *,
    created_by_install: bool,
) -> Dict[str, Any]:
    """Plan exact prior-record removal plus current-record convergence."""
    if settings_rel not in SETTINGS_FILE_BY_HOOKS_KEY.values():
        raise ProjectInstallError(f"unknown hook settings path {settings_rel!r}")
    validate_hooks_subtree(
        hooks_subtree,
        entry_format=hook_entry_format(settings_rel),
    )
    assert_resolved_targets_within(
        repo_root,
        [settings_rel],
        context="hook settings mutation",
    )
    target = repo_root / settings_rel
    materialize = target.is_symlink()
    current_records = provided_records(hooks_subtree)
    current_keys = {record_key(record) for record in current_records}
    stale_keys = {
        record_key(record)
        for record in prior_records
        if record_key(record) not in current_keys
    }
    if target.is_file():
        payload = _validated_settings_payload(target)
        created = False
    else:
        payload = _empty_payload(settings_rel)
        created = bool(current_records)
    hooks = payload.setdefault("hooks", {})
    assert isinstance(hooks, dict)
    removed: List[Dict[str, Any]] = []
    for event in list(hooks):
        entries = hooks[event]
        assert isinstance(entries, list)
        kept = []
        for entry in entries:
            if (event, *_entry_key(entry)) in stale_keys:
                removed.append(_record(event, entry))
            else:
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]

    added: List[Dict[str, Any]] = []
    for event in sorted(hooks_subtree):
        entries = hooks.setdefault(event, [])
        existing = {_entry_key(entry) for entry in entries}
        for entry in hooks_subtree[event]:
            if _entry_key(entry) in existing:
                continue
            entries.append(entry)
            existing.add(_entry_key(entry))
            added.append(_record(event, entry))
    empty_payload = _empty_payload(settings_rel)
    deleted_file = created_by_install and payload == empty_payload
    return {
        "created": created,
        "added": added,
        "removed": removed,
        "deleted_file": deleted_file,
        "changed": bool(
            created or added or removed or deleted_file or materialize
        ),
        "materialized": materialize,
        "payload": payload,
    }


def reconcile_hooks_file(
    repo_root: Path,
    settings_rel: str,
    hooks_subtree: Dict[str, Any],
    prior_records: List[Dict[str, Any]],
    *,
    created_by_install: bool,
) -> Dict[str, Any]:
    """Replace prior Yoke hook ownership with the selected bundle records."""
    result = plan_hooks_file(
        repo_root,
        settings_rel,
        hooks_subtree,
        prior_records,
        created_by_install=created_by_install,
    )
    target = repo_root / settings_rel
    if result["deleted_file"] and target.is_file():
        target.unlink()
        from yoke_cli.project_install.files import remove_empty_parents

        remove_empty_parents(repo_root, settings_rel)
    elif result["changed"]:
        _write_settings(target, result["payload"])
    return {key: value for key, value in result.items() if key != "payload"}


def preflight_hooks_settings(
    repo_root: Path,
    bundle_hooks: Dict[str, Any],
    prior_hook_entries: Dict[str, List[Dict[str, Any]]],
    created_settings: set[str],
) -> Dict[str, Dict[str, Any]]:
    """Validate and plan every settings mutation without writing."""
    plans = {}
    for hooks_key, settings_rel in sorted(SETTINGS_FILE_BY_HOOKS_KEY.items()):
        plans[settings_rel] = plan_hooks_file(
            repo_root,
            settings_rel,
            bundle_hooks[hooks_key],
            list(prior_hook_entries.get(settings_rel, [])),
            created_by_install=settings_rel in created_settings,
        )
    return plans


def merge_hooks_file(
    repo_root: Path, settings_rel: str, hooks_subtree: Dict[str, Any]
) -> Dict[str, Any]:
    """Ensure every bundle hook entry exists in the project settings file.

    Returns ``{"created": bool, "added": [records]}``. Operator-authored
    entries are never removed or reordered; missing bundle entries append
    at the end of their event's array.
    """
    validate_hooks_subtree(
        hooks_subtree,
        entry_format=hook_entry_format(settings_rel),
    )
    assert_resolved_targets_within(
        repo_root,
        [settings_rel],
        context="hook settings mutation",
    )
    target = repo_root / settings_rel
    if not target.is_file():
        _write_settings(
            target,
            {
                **(DEFAULT_PAYLOAD_BY_SETTINGS_REL.get(settings_rel) or {}),
                "hooks": hooks_subtree,
            },
        )
        return {
            "created": True,
            "added": provided_records(hooks_subtree),
        }
    payload = _validated_settings_payload(target)
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
    if added or target.is_symlink():
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
    assert_resolved_targets_within(
        repo_root,
        [settings_rel],
        context="hook settings removal",
    )
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
            if isinstance(entry, dict) and (event, *_entry_key(entry)) in record_keys:
                removed.append(_record(event, entry))
                continue
            kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]  # event held only Yoke entries
    if not removed:
        return {"removed": [], "deleted_file": False}
    if created_by_install and payload == _empty_payload(settings_rel):
        target.unlink()
        from yoke_cli.project_install.files import remove_empty_parents

        remove_empty_parents(repo_root, settings_rel)
        return {"removed": removed, "deleted_file": True}
    _write_settings(target, payload)
    return {"removed": removed, "deleted_file": False}


__all__ = [
    "CLAUDE_SETTINGS_REL",
    "CODEX_HOOKS_REL",
    "CURSOR_HOOKS_REL",
    "SETTINGS_FILE_BY_HOOKS_KEY",
    "demerge_hooks_file",
    "merge_hooks_file",
    "plan_hooks_file",
    "preflight_hooks_settings",
    "provided_records",
    "reconcile_hooks_file",
    "record_key",
    "hook_entry_format",
    "validate_hooks_subtree",
]
