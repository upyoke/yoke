"""Yoke-managed permissions region inside ``.claude/settings.json``.

The bundle's hook subtree flows through :mod:`hooks`; this module owns the
sibling ``permissions.allow`` list and the ``autoMemoryEnabled`` flag that the
documented autonomous + streaming flow needs (without them a fresh project
prompts on every ``Bash`` / ``Write`` / ``Edit`` / ``Monitor`` call, stalling
the flow). It follows the same "manage exactly our region, never the operator's
keys" contract as the hook merge:

* ``permissions.allow`` — union in the entries Yoke renders and remove the
  entries a previous install recorded that the current bundle no longer
  renders; an entry Yoke never recorded is operator-authored and is never
  removed or reordered, and refresh is idempotent.
* ``autoMemoryEnabled`` — seed to the bundle value only when the key is absent;
  an operator's explicit choice is never overwritten.

The install manifest records the full allow set this pass renders
(``rendered_allow``) and whether it seeded the flag, so the next refresh can
retire entries Yoke stopped rendering and uninstall removes the recorded set.
File creation/deletion of ``.claude/settings.json`` itself is
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
    target.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline=""
    )


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
    payload: Optional[Dict[str, Any]],
    managed: Dict[str, Any],
    prior_record: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Return (new_payload, record) — pure, no IO.

    ``record`` names what this pass adds and removes: an entry the prior
    record's ``rendered_allow`` carries that ``managed`` no longer renders is
    retired; an entry absent from that record is the operator's and stays.
    """
    allow_wanted, auto_wanted = _validate(managed)
    prior = prior_record if isinstance(prior_record, dict) else {}
    retired = [
        entry
        for entry in prior.get("rendered_allow") or []
        if entry not in allow_wanted
    ]
    payload = dict(payload) if payload else {}
    permissions = dict(payload.get("permissions") or {})
    created_permissions = "permissions" not in payload
    existing_allow = list(permissions.get("allow") or [])
    kept = [entry for entry in existing_allow if entry not in retired]
    removed = [entry for entry in existing_allow if entry in retired]
    added = [entry for entry in allow_wanted if entry not in kept]
    permissions["allow"] = kept + added
    payload["permissions"] = permissions
    set_auto = False
    if auto_wanted is not None and "autoMemoryEnabled" not in payload:
        payload["autoMemoryEnabled"] = auto_wanted
        set_auto = True
    record = {
        "rendered_allow": allow_wanted,
        "added_allow": added,
        "removed_allow": removed,
        "set_auto_memory": set_auto,
        "created_permissions": created_permissions and bool(added),
    }
    return payload, record


def _summary(record: Dict[str, Any], *, preview: bool) -> str:
    """Name the allow-list and flag changes a plan makes, for action lines."""
    bits = []
    if record["added_allow"]:
        verb = "allow" if preview else "allowed"
        bits.append(f"{verb} {len(record['added_allow'])} Yoke tool(s)")
    if record["removed_allow"]:
        verb = "remove" if preview else "removed"
        bits.append(f"{verb} {len(record['removed_allow'])} retired Yoke permission(s)")
    if record["set_auto_memory"]:
        bits.append("set autoMemoryEnabled")
    return ", ".join(bits) or "permissions"


def _changes(record: Dict[str, Any]) -> bool:
    return bool(
        record["added_allow"] or record["removed_allow"] or record["set_auto_memory"]
    )


def apply_settings_permissions(
    repo_root: Path,
    managed: Optional[Dict[str, Any]],
    prior_record: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Reconcile our permissions region into ``.claude/settings.json``.

    Returns ``(record, report)``. ``record`` (manifest-persisted) carries the
    full rendered allow set so the next refresh retires what Yoke stops
    rendering and uninstall removes it. ``report`` carries the user-facing
    action line.
    """
    if not managed:
        return {}, {"actions": [], "changed": False}
    assert_resolved_targets_within(
        repo_root,
        [CLAUDE_SETTINGS_REL],
        context="settings permissions mutation",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    created_file = payload is None
    new_payload, current = _plan(payload, managed, prior_record)
    changed = _changes(current) or created_file
    prior = prior_record if isinstance(prior_record, dict) else {}
    record = {
        "rendered_allow": current["rendered_allow"],
        "set_auto_memory": bool(
            prior.get("set_auto_memory") or current["set_auto_memory"]
        ),
        "created_permissions": bool(
            prior.get("created_permissions") or current["created_permissions"]
        ),
        "created_file": bool(prior.get("created_file") or created_file),
    }
    if changed:
        _write(target, new_payload)
        action = (
            f"Updated: {CLAUDE_SETTINGS_REL} ({_summary(current, preview=False)}; "
            "your other settings preserved)"
        )
    else:
        action = f"Exists: {CLAUDE_SETTINGS_REL} (Yoke tool permissions up to date)"
    return record, {"actions": [action], "changed": changed}


def preview_settings_permissions(
    repo_root: Path,
    managed: Optional[Dict[str, Any]],
    prior_record: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan the permissions mutation without writing (review/preview)."""
    if not managed:
        return {"actions": [], "would_change": False}
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    _new_payload, record = _plan(payload, managed, prior_record)
    would_change = _changes(record) or payload is None
    if would_change:
        line = (
            f"Would update: {CLAUDE_SETTINGS_REL} ({_summary(record, preview=True)}; "
            "your other settings preserved)"
        )
    else:
        line = f"Would keep: {CLAUDE_SETTINGS_REL} (Yoke tool permissions up to date)"
    return {"actions": [line], "would_change": would_change}


def remove_settings_permissions(
    repo_root: Path,
    record: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Uninstall pass: remove the recorded allow set and the flag we seeded.

    Runs BEFORE the hook de-merge so that, once our region is gone, the hook
    de-merge's "delete when only an empty hooks block remains" check can fire.
    Deletes the file itself only if this pass created it and nothing remains.
    """
    if not record:
        return {"removed_allow": [], "unset_auto_memory": False, "deleted_file": False}
    assert_resolved_targets_within(
        repo_root,
        [CLAUDE_SETTINGS_REL],
        context="settings permissions removal",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    if payload is None:
        return {"removed_allow": [], "unset_auto_memory": False, "deleted_file": False}
    rendered_allow = list(record.get("rendered_allow") or [])
    removed: List[str] = []
    permissions = payload.get("permissions")
    if isinstance(permissions, dict) and isinstance(permissions.get("allow"), list):
        kept = [entry for entry in permissions["allow"] if entry not in rendered_allow]
        removed = [entry for entry in permissions["allow"] if entry in rendered_allow]
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
