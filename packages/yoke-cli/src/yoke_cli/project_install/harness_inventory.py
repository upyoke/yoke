"""Client-side harness presence for install persist and the upsert adapter.

Lives in the CLI package so product install never imports ``yoke_core``.
Codex is approved only when every normalized hook handler matches the
``trusted_hash`` stored for this checkout's literal ``.codex/hooks.json``
path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_contracts.harness_unattended_posture import posture_state
from typing import Any, Optional

from yoke_contracts.codex_hook_trust import (
    codex_hooks_are_approved,
    normalized_codex_hook_hashes,
)

try:
    import tomllib
except ImportError:  # Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


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
    if not _exists(path):
        return None, False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None, True
    if not isinstance(payload, dict):
        return None, True
    return payload, False


def _codex_hooks(checkout: Path) -> Path:
    return checkout / ".codex" / "hooks.json"


def _codex_trust_entries(hooks: Path) -> dict[str, str]:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config = home / "config.toml"
    if tomllib is None or not _exists(config):
        return {}
    try:
        with config.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return {}
    state = ((data.get("hooks") or {}).get("state")) or {}
    if not isinstance(state, dict):
        return {}
    prefix = f"{hooks}:"
    entries: dict[str, str] = {}
    for key, entry in state.items():
        if not isinstance(key, str) or not key.startswith(prefix):
            continue
        trusted_hash = entry.get("trusted_hash") if isinstance(entry, dict) else None
        if isinstance(trusted_hash, str) and trusted_hash:
            entries[key[len(prefix) :]] = trusted_hash
    return entries


def _codex_report(checkout: Path) -> Optional[dict[str, Any]]:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config_present = _dir_present(home) or _exists(home / "config.toml")
    hooks = _codex_hooks(checkout)
    glue_present = _exists(hooks)
    payload, malformed = _json_object(hooks) if glue_present else (None, False)
    if glue_present and payload is not None and "hooks" not in payload:
        malformed = True
    if payload is not None and normalized_codex_hook_hashes(payload) is None:
        malformed = True
    approval = "not_applicable"
    if glue_present:
        approval = (
            "approved"
            if codex_hooks_are_approved(payload, _codex_trust_entries(hooks))
            else "unapproved"
        )
    if not (config_present or glue_present):
        return None
    return {
        "harness_id": "codex",
        "unattended_posture": posture_state("codex"),
        "glue_present": glue_present,
        "glue_malformed": malformed,
        "config_present": config_present,
        "project_entry_present": False,
        "approval_state": approval,
    }


def _claude_config_path() -> Path:
    explicit = os.environ.get("CLAUDE_CONFIG_PATH")
    if explicit:
        return Path(explicit).expanduser()
    config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
    if config_dir:
        return Path(config_dir).expanduser() / ".claude.json"
    return Path.home() / ".claude.json"


def _claude_ran_here(checkout: Path) -> bool:
    payload, malformed = _json_object(_claude_config_path())
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
    config_path = _claude_config_path()
    config_present = _exists(config_path) or _dir_present(config_path.parent)
    glue = checkout / ".claude" / "settings.json"
    payload, malformed = _json_object(glue)
    glue_present = payload is not None or malformed
    project_entry = _claude_ran_here(checkout)
    if not (config_present or glue_present or project_entry):
        return None
    return {
        "harness_id": "claude-code",
        "unattended_posture": posture_state("claude-code"),
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
        "unattended_posture": posture_state("cursor"),
        "glue_present": glue_present,
        "glue_malformed": malformed,
        "config_present": config_present,
        "project_entry_present": False,
        "approval_state": "not_applicable",
    }


def collect_harness_inventory(checkout: str | Path) -> list[dict[str, Any]]:
    root = Path(checkout)
    reports: list[dict[str, Any]] = []
    for report in (_codex_report(root), _claude_report(root), _cursor_report()):
        if report is not None:
            reports.append(report)
    return reports


def collect_pack_prerequisite_inventory(
    checkout: str | Path,
) -> list[dict[str, Any]]:
    """Return installed Pack tool readiness for this machine and checkout."""
    from yoke_cli.packs.prerequisites import collect_installed_pack_prerequisites

    return collect_installed_pack_prerequisites(checkout)


__all__ = ["collect_harness_inventory", "collect_pack_prerequisite_inventory"]
