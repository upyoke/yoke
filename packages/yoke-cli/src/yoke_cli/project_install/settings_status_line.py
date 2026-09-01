"""Yoke-managed ``statusLine`` inside a project's ``.claude/settings.json``.

Claude states the context window it is serving in exactly one
machine-readable place — the JSON it pipes to the configured status line
command — so an installed project with no status line has no way to attest
``harness_sessions.context_window_tokens`` for any Claude session. This pass
installs Yoke's, which records that window and prints the model, window and
usage in exchange for the slot.

``statusLine`` is single-valued, so this follows the ``autoMemoryEnabled``
rule rather than the ``permissions.allow`` union rule: seed it only when the
key is absent, and never overwrite a status line the operator authored. An
operator who wants their own after the fact sets ``statusLine`` in
``.claude/settings.local.json``, which outranks the project file — and gives
up the attestation with it, which is why that trade is named in the install
report rather than left to be discovered.

The manifest records whether this pass seeded the key, so uninstall removes
exactly what Yoke put there and never an operator's own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_cli.project_install.files import (
    ProjectInstallError,
    assert_resolved_targets_within,
)
from yoke_cli.project_install.hooks import CLAUDE_SETTINGS_REL


#: Bundle key carrying the managed status line command.
MANAGED_STATUS_LINE_KEY = "claude_settings_status_line"

#: Manifest key recording what this pass seeded.
STATUS_LINE_MANIFEST_KEY = "settings_status_line"

_SETTINGS_FIELD = "statusLine"


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


def _validate(managed: Any) -> Dict[str, Any]:
    if not isinstance(managed, dict):
        raise ProjectInstallError(f"{MANAGED_STATUS_LINE_KEY} must be an object")
    command = managed.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ProjectInstallError(
            f"{MANAGED_STATUS_LINE_KEY}.command must be a non-empty string"
        )
    if managed.get("type") != "command":
        raise ProjectInstallError(f'{MANAGED_STATUS_LINE_KEY}.type must be "command"')
    return dict(managed)


def _seeds(payload: Optional[Dict[str, Any]]) -> bool:
    """True when the settings file has no status line of its own yet."""
    return payload is None or _SETTINGS_FIELD not in payload


def apply_settings_status_line(
    repo_root: Path,
    managed: Optional[Dict[str, Any]],
    prior_record: Optional[Dict[str, Any]] = None,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Seed Yoke's status line when the project has none of its own.

    Returns ``(record, report)``. The record names whether this pass seeded
    the key, so uninstall removes precisely that.
    """
    if not managed:
        return {}, {"actions": [], "changed": False}
    wanted = _validate(managed)
    assert_resolved_targets_within(
        repo_root,
        [CLAUDE_SETTINGS_REL],
        context="settings status line mutation",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    prior = prior_record if isinstance(prior_record, dict) else {}
    seeded_before = bool(prior.get("seeded"))
    actions: List[str] = []

    if not _seeds(payload):
        # Either Yoke's own line from an earlier install (converge it to the
        # current command, since the record says the key is ours) or one the
        # operator wrote (leave it, and say so — a silently ignored status
        # line is how an operator concludes the attestation is broken).
        assert payload is not None
        if seeded_before:
            changed = payload.get(_SETTINGS_FIELD) != wanted
            if changed:
                payload[_SETTINGS_FIELD] = wanted
                _write(target, payload)
                actions.append(
                    f"Updated: {CLAUDE_SETTINGS_REL} (Yoke status line refreshed)"
                )
            else:
                actions.append(
                    f"Exists: {CLAUDE_SETTINGS_REL} (Yoke status line up to date)"
                )
            return {"seeded": True}, {"actions": actions, "changed": changed}
        actions.append(
            f"Kept: {CLAUDE_SETTINGS_REL} statusLine (yours; Claude allows one, "
            "so served context_window_tokens stays unattested for this project)"
        )
        return {"seeded": False}, {"actions": actions, "changed": False}

    payload = dict(payload or {})
    payload[_SETTINGS_FIELD] = wanted
    _write(target, payload)
    actions.append(
        f"Updated: {CLAUDE_SETTINGS_REL} (set statusLine; it records the served "
        "context window and prints model, window and usage)"
    )
    return {"seeded": True}, {"actions": actions, "changed": True}


def preview_settings_status_line(
    repo_root: Path,
    managed: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Plan the status line mutation without writing (review/preview)."""
    if not managed:
        return {"actions": [], "would_change": False}
    _validate(managed)
    payload = _load(repo_root / CLAUDE_SETTINGS_REL)
    if _seeds(payload):
        return {
            "actions": [
                f"Would update: {CLAUDE_SETTINGS_REL} (set statusLine; it "
                "records the served context window)"
            ],
            "would_change": True,
        }
    return {
        "actions": [f"Would keep: {CLAUDE_SETTINGS_REL} statusLine (already set)"],
        "would_change": False,
    }


def remove_settings_status_line(
    repo_root: Path,
    record: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Uninstall pass: remove the status line only if this pass seeded it."""
    if not isinstance(record, dict) or not record.get("seeded"):
        return {"removed": False}
    assert_resolved_targets_within(
        repo_root,
        [CLAUDE_SETTINGS_REL],
        context="settings status line removal",
    )
    target = repo_root / CLAUDE_SETTINGS_REL
    payload = _load(target)
    if payload is None or _SETTINGS_FIELD not in payload:
        return {"removed": False}
    payload.pop(_SETTINGS_FIELD, None)
    _write(target, payload)
    return {"removed": True}


def _write(target: Path, payload: Dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "MANAGED_STATUS_LINE_KEY",
    "STATUS_LINE_MANIFEST_KEY",
    "apply_settings_status_line",
    "preview_settings_status_line",
    "remove_settings_status_line",
]
