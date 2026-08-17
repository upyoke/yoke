"""Client-side harness presence for install persist and the upsert adapter.

Lives in the CLI package so product install never imports ``yoke_core``.
Presence only: Codex is unapproved when glue exists and no ``hooks.state``
key names this checkout's literal ``.codex/hooks.json`` path.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

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


def _codex_trusted(hooks: Path) -> bool:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config = home / "config.toml"
    if tomllib is None or not _exists(config):
        return False
    try:
        with config.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, ValueError):
        return False
    state = ((data.get("hooks") or {}).get("state")) or {}
    if not isinstance(state, dict):
        return False
    prefix = f"{hooks}:"
    return any(isinstance(key, str) and key.startswith(prefix) for key in state)


def _codex_report(checkout: Path) -> Optional[dict[str, Any]]:
    home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    config_present = _dir_present(home) or _exists(home / "config.toml")
    hooks = _codex_hooks(checkout)
    glue_present = _exists(hooks)
    payload, malformed = _json_object(hooks) if glue_present else (None, False)
    if glue_present and payload is not None and "hooks" not in payload:
        malformed = True
    approval = "not_applicable"
    if glue_present:
        approval = "approved" if _codex_trusted(hooks) else "unapproved"
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
    root = Path(checkout)
    reports: list[dict[str, Any]] = []
    for report in (_codex_report(root), _claude_report(root), _cursor_report()):
        if report is not None:
            reports.append(report)
    return reports
