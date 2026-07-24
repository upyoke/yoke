"""Yoke-managed permissions region inside ``.claude/settings.json``.

The bundle's hook subtree flows through :mod:`hooks`; this module owns the
sibling ``permissions.allow`` list and the ``autoMemoryEnabled`` flag that the
documented autonomous + streaming flow needs (without them a fresh project
prompts on every ``Bash`` / ``Write`` / ``Edit`` / ``Monitor`` call, stalling
the flow). It follows the same "manage exactly our region, never the operator's
keys" contract as the hook merge:

* ``permissions.allow`` — union in the entries Yoke requires; an operator's own
  allow entries are never removed or reordered, and refresh is idempotent.
* ``autoMemoryEnabled`` — seed to the bundle value only when the key is absent;
  an operator's explicit choice is never overwritten.

The install manifest records exactly what this pass added (which allow entries,
whether it seeded the flag) so uninstall removes precisely that and nothing an
operator authored. File creation/deletion of ``.claude/settings.json`` itself is
owned by :mod:`hooks` (the hook merge always runs first and creates it); this
pass only mutates the region when the file already exists in the normal flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
    remove_empty_parents,
)
from yoke_cli.project_install.hooks import CLAUDE_SETTINGS_REL

# Bundle key carrying the managed permissions region.
MANAGED_PERMISSIONS_KEY = "claude_settings_permissions"


def _load(target: Path) -> Optional[Dict[str, Any]]:
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProjectInstallError(
            f"{target} is not valid JSON ({exc}); repair it before rerunning "
            "`yoke project install`"
        ) from exc
    if not isinstance(payload, dict):
        raise ProjectInstallError(f"{target} must contain a JSON object")
    return payload


def _write(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _validate(managed: Any) -> Tuple[List[str], Optional[bool]]:
    if not isinstance(managed, dict):
        raise ProjectInstallError("claude_settings_permissions must be an object")
    allow = managed.get("allow", [])
    if not isinstance(allow, list) or not all(
        isinstance(entry, str) and entry for entry in allow
    ):
        raise ProjectInstallError(
            "claude_settings_permissions.allow must be a list of non-empty strings"
        )
    auto = managed.get("auto_memory_enabled")
    if auto is not None and not isinstance(auto, bool):
        raise ProjectInstallError(
            "claude_settings_permissions.auto_memory_enabled must be a boolean"
        )
    return list(allow), auto


def _plan(
    payload: Optional[Dict[str, Any]], managed: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (new_payload, record) — pure, no IO. ``record`` names what we add."""
    allow_wanted, auto_wanted = _validate(managed)
    payload = dict(payload) if payload else {}
    permissions = dict(payload.get("permissions") or {})
    created_permissions = "permissions" not in payload
    existing_allow = list(permissions.get("allow") or [])
    added = [entry for entry in allow_wanted if entry not in existing_allow]
    permissions["allow"] = existing_allow + added
    payload["permissions"] = permissions
    set_auto = False
    if auto_wanted is not None and "autoMemoryEnabled" not in payload:
        payload["autoMemoryEnabled"] = auto_wanted
        set_auto = True
    record = {
        "added_allow": added,
        "set_auto_memory": set_auto,
        "created_permissions": created_permissions and bool(added),
    }
    return payload, record


def apply_settings_permissions(
    repo_root: Path, managed: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Union our permissions region into ``.claude/settings.json``.

    Returns ``(record, report)``. ``record`` (manifest-persisted) names exactly
    what was added so uninstall is precise. ``report`` carries the user-facing
    action line and the added counts.
    """
    if not managed:
        return {}, {"actions": [], "changed": False}
    assert_resolved_targets_within(
        repo_root, [CLAUDE_SETTINGS_REL], context="settings permissions mutation",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    created_file = payload is None
    new_payload, record = _plan(payload, managed)
    record["created_file"] = created_file
    changed = bool(record["added_allow"]) or record["set_auto_memory"] or created_file
    actions: List[str] = []
    if changed:
        _write(target, new_payload)
        added_n = len(record["added_allow"])
        bits = []
        if added_n:
            bits.append(f"allowed {added_n} Yoke tool(s)")
        if record["set_auto_memory"]:
            bits.append("set autoMemoryEnabled")
        actions.append(
            f"Updated: {CLAUDE_SETTINGS_REL} ({', '.join(bits) or 'permissions'}; "
            "your other settings preserved)"
        )
    else:
        actions.append(
            f"Exists: {CLAUDE_SETTINGS_REL} (Yoke tool permissions up to date)"
        )
    return record, {"actions": actions, "changed": changed}


def preview_settings_permissions(
    repo_root: Path, managed: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Plan the permissions mutation without writing (review/preview)."""
    if not managed:
        return {"actions": [], "would_change": False}
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    _new_payload, record = _plan(payload, managed)
    would_change = (
        bool(record["added_allow"]) or record["set_auto_memory"] or payload is None
    )
    added_n = len(record["added_allow"])
    if would_change:
        bits = []
        if added_n:
            bits.append(f"allow {added_n} Yoke tool(s)")
        if record["set_auto_memory"] or payload is None:
            bits.append("set autoMemoryEnabled")
        line = (
            f"Would update: {CLAUDE_SETTINGS_REL} ({', '.join(bits)}; "
            "your other settings preserved)"
        )
    else:
        line = f"Would keep: {CLAUDE_SETTINGS_REL} (Yoke tool permissions up to date)"
    return {"actions": [line], "would_change": would_change}


def remove_settings_permissions(
    repo_root: Path, record: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Uninstall pass: remove exactly the allow entries and flag we added.

    Runs BEFORE the hook de-merge so that, once our region is gone, the hook
    de-merge's "delete when only an empty hooks block remains" check can fire.
    Deletes the file itself only if this pass created it and nothing remains.
    """
    if not record:
        return {"removed_allow": [], "unset_auto_memory": False, "deleted_file": False}
    assert_resolved_targets_within(
        repo_root, [CLAUDE_SETTINGS_REL], context="settings permissions removal",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    if payload is None:
        return {"removed_allow": [], "unset_auto_memory": False, "deleted_file": False}
    added_allow = list(record.get("added_allow") or [])
    removed: List[str] = []
    permissions = payload.get("permissions")
    if isinstance(permissions, dict) and isinstance(permissions.get("allow"), list):
        kept = [entry for entry in permissions["allow"] if entry not in added_allow]
        removed = [entry for entry in permissions["allow"] if entry in added_allow]
        if kept:
            permissions["allow"] = kept
        else:
            permissions.pop("allow", None)
        if record.get("created_permissions") and not permissions:
            payload.pop("permissions", None)
        else:
            payload["permissions"] = permissions
    unset_auto = False
    if record.get("set_auto_memory") and "autoMemoryEnabled" in payload:
        payload.pop("autoMemoryEnabled", None)
        unset_auto = True
    deleted_file = False
    if record.get("created_file") and not payload:
        target.unlink()
        remove_empty_parents(repo_root, CLAUDE_SETTINGS_REL)
        deleted_file = True
    elif removed or unset_auto:
        _write(target, payload)
    return {
        "removed_allow": removed,
        "unset_auto_memory": unset_auto,
        "deleted_file": deleted_file,
    }


__all__ = [
    "CLAUDE_SETTINGS_REL",
    "MANAGED_PERMISSIONS_KEY",
    "apply_settings_permissions",
    "preview_settings_permissions",
    "remove_settings_permissions",
]
