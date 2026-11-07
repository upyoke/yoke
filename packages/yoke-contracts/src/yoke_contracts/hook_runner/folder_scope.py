"""Machine-local folder policy shared by every hook transport and harness."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.checkout import main_checkout
from yoke_contracts.machine_config.selection import connection_groups, checkout_connection
from yoke_contracts.hook_runner.project_scope import workspace_path_candidates

DISABLED_FOLDERS_KEY = "disabled_folders"


def disabled_folder(path: str | Path, config: Mapping[str, Any]) -> str:
    """Return the disabled ancestor covering a physical folder, if any."""
    current = Path(path).expanduser().resolve()
    for value in config.get(DISABLED_FOLDERS_KEY, []):
        if isinstance(value, str) and current.is_relative_to(Path(value).expanduser().resolve()):
            return value
    return ""


def folder_scope(stdin_data: str = "", *, path: str | Path | None = None) -> str:
    """Return disabled, unregistered or registered; preserve existing error handling."""
    try:
        payload = json.loads(stdin_data) if stdin_data else {}
        config = machine_config.load_config()
        candidates = workspace_path_candidates(payload if isinstance(payload, dict) else {})
        candidates.append(str(path or os.getcwd()))
        if any(disabled_folder(value, config) for value in candidates):
            return "disabled"
        # Explicitly launched org-scoped children retain their launch connection.
        if os.environ.get("YOKE_ENV", "").strip() or os.environ.get("YOKE_SESSION_LAUNCH_CONTEXT", "").strip():
            return "registered"
        for value in candidates:
            current = Path(value).expanduser().resolve()
            connection = checkout_connection(config, current)
            if not connection:
                continue
            primary = main_checkout(current)
            if any((parent / ".git").exists() for parent in (current, *current.parents)):
                if not any(
                    Path(entry["checkout"]).expanduser().resolve() == primary
                    for entry in connection_groups(config)[connection]
                ):
                    continue
            return "registered"
        return "unregistered"
    except (ValueError, OSError, RuntimeError, TypeError):
        return "registered"
