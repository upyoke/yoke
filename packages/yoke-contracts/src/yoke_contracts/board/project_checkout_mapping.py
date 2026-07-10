"""Resolve project ids to existing local checkouts from machine config."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

from yoke_contracts.machine_config.schema import normalize_project_id


def configured_project_checkouts(config: dict) -> Dict[int, str]:
    """Return existing checkout paths keyed by normalized project id."""
    projects = config.get("projects", {})
    out: Dict[int, str] = {}
    if not isinstance(projects, dict):
        return out
    for checkout, entry in sorted(projects.items()):
        if not isinstance(entry, dict):
            continue
        project_id = normalize_project_id(entry.get("project_id"))
        if project_id is None:
            continue
        path = Path(str(checkout)).expanduser()
        if path.is_dir():
            out[int(project_id)] = str(path)
    return out


__all__ = ["configured_project_checkouts"]
