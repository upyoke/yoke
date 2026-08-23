"""Collect machine-side harness evidence from the local filesystem.

Codex approval requires an exact match between every normalized hook handler
and the ``trusted_hash`` stored under this checkout's literal
``.codex/hooks.json`` path.  The path is not symlink-resolved. Cursor glue is
the user-level ``~/.cursor/hooks.json``; ``~/.cursor/projects/`` is not
consulted because it is not confirmed to key by project path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.codex_hook_trust import (
    codex_hooks_are_approved,
    normalized_codex_hook_hashes,
)
from yoke_core.domain.worktree_claude_approval import claude_config_path
from yoke_core.domain.worktree_codex_hook_trust import (
    hooks_file_for,
    trust_entries_for,
)


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _dir_present(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _json_object(path: Path) -> tuple[Optional[dict[str, Any]], bool]:
    """Return ``(payload, malformed)``. Missing is ``(None, False)``."""
    if not _exists(path):
        return None, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, True
    if not isinstance(payload, dict):
        return None, True
    return payload, False


def _codex_report(checkout: Path) -> Optional[dict[str, Any]]:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config_present = _dir_present(home) or _exists(home / "config.toml")
    hooks = hooks_file_for(str(checkout))
    glue_present = _exists(hooks)
    payload, malformed = _json_object(hooks) if glue_present else (None, False)
    if glue_present and payload is not None and "hooks" not in payload:
        malformed = True
    if payload is not None and normalized_codex_hook_hashes(payload) is None:
        malformed = True
    approval = "not_applicable"
    if glue_present:
        entries = trust_entries_for(hooks)
        approval = (
            "approved" if codex_hooks_are_approved(payload, entries) else "unapproved"
        )
    if not (config_present or glue_present):
        return None
    return {
        "harness_id": "codex",
        "glue_present": glue_present,
        "glue_malformed": malformed,
        "config_present": config_present,
        "project_entry_present": False,
        "approval_state": approval,
    }


def _claude_ran_here(checkout: Path) -> bool:
    payload, malformed = _json_object(claude_config_path())
    if malformed or not payload:
        return False
    projects = payload.get("projects")
    if not isinstance(projects, dict):
        return False
    candidates = {str(checkout), str(checkout.expanduser())}
    try:
        candidates.add(str(checkout.expanduser().resolve()))
    except OSError:
        pass
    return any(key in projects for key in candidates)


def _claude_report(checkout: Path) -> Optional[dict[str, Any]]:
    config_path = claude_config_path()
    config_present = _exists(config_path) or _dir_present(config_path.parent)
    glue = checkout / ".claude" / "settings.json"
    payload, malformed = _json_object(glue)
    glue_present = payload is not None or malformed
    project_entry = _claude_ran_here(checkout)
    if not (config_present or glue_present or project_entry):
        return None
    return {
        "harness_id": "claude-code",
        "glue_present": glue_present,
        "glue_malformed": malformed,
        "config_present": config_present,
        "project_entry_present": project_entry,
        "approval_state": "not_applicable",
    }


def _cursor_report() -> Optional[dict[str, Any]]:
    root = Path.home() / ".cursor"
    config_present = _dir_present(root)
    glue = root / "hooks.json"
    payload, malformed = _json_object(glue)
    glue_present = payload is not None or malformed
    if not (config_present or glue_present):
        return None
    return {
        "harness_id": "cursor",
        "glue_present": glue_present,
        "glue_malformed": malformed,
        "config_present": config_present,
        "project_entry_present": False,
        "approval_state": "not_applicable",
    }


def collect_harness_inventory(checkout: str | Path) -> list[dict[str, Any]]:
    """Return one report per harness that has machine-side evidence."""
    root = Path(checkout)
    reports: list[dict[str, Any]] = []
    for report in (_codex_report(root), _claude_report(root), _cursor_report()):
        if report is not None:
            reports.append(report)
    return reports


__all__ = ["collect_harness_inventory"]
