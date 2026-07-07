"""Read-side DB helpers for observe telemetry attribution."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_core.domain.observe_db import normalize_observe_db_path


def connect_observe_read_db(db_path: Optional[str]):
    """Connect for observe read-side attribution.

    The path is a routing token for the backend factory, not a raw SQLite file
    authority. Live hooks and Postgres tests both resolve through the selected
    Yoke backend; callers stay fail-open by catching connection/query errors.
    """
    normalized = normalize_observe_db_path(db_path)

    from yoke_core.domain.db_helpers import connect

    return connect(normalized)


def repo_root_for_attribution(db_path: str, project_dir: str) -> Optional[str]:
    """Resolve the main repo root for observe main-session attribution."""
    if db_path:
        try:
            db_file = Path(db_path).expanduser().resolve()
        except OSError:
            db_file = None
        if (
            db_file
            and db_file.name == "yoke.db"
            and db_file.parent.name == "data"
        ):
            return str(db_file.parent.parent)
    try:
        from yoke_core.domain.worktree import resolve_main_root

        return resolve_main_root(cwd=project_dir, claude_project_dir="")
    except Exception:
        return project_dir


__all__ = ["connect_observe_read_db", "repo_root_for_attribution"]
