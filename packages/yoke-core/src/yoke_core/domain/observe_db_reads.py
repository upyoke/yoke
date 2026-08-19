"""Read-side DB helpers for observe telemetry attribution."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from yoke_core.domain import db_backend
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


def compute_tool_call_duration(
    db_path: Optional[str], tool_use_id: str,
) -> Optional[int]:
    """Return tool-call duration from explicit or connected authority state."""
    try:
        conn = connect_observe_read_db(db_path)
        try:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                """SELECT started_at FROM session_tool_calls
                   WHERE tool_use_id = {marker}
                   ORDER BY started_at DESC LIMIT 1""".format(marker=marker),
                (tool_use_id,),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            start_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            duration_ms = int(
                (datetime.now(timezone.utc) - start_dt).total_seconds() * 1000
            )
            if 0 <= duration_ms <= 600000:
                return duration_ms
    except Exception:
        pass
    return None


def repo_root_for_attribution(db_path: str, project_dir: str) -> Optional[str]:
    """Resolve the main repo root for observe main-session attribution."""
    if db_path:
        try:
            db_file = Path(db_path).expanduser().resolve()
        except OSError:
            db_file = None
        if db_file and db_file.name == "yoke.db" and db_file.parent.name == "data":
            return str(db_file.parent.parent)
    try:
        from yoke_core.domain.worktree import resolve_main_root

        return resolve_main_root(cwd=project_dir, claude_project_dir="")
    except Exception:
        return project_dir


def worktree_path_item_id(file_path: str, db_path: Optional[str]) -> Optional[int]:
    """Attribute a file path under ``.worktrees/<name>/`` to its owning item.

    Reverse-looks up the recorded worktree/branch name so both the public-ref
    scheme and the legacy ``YOK-{internal_id}`` scheme resolve to the correct
    internal id; falls back to a bare legacy-name parse when no DB is
    available (attribution without a connection).
    """
    import re

    match = re.search(r"\.worktrees/([^/]+)/", file_path or "")
    if not match:
        return None
    name = match.group(1)
    if db_path:
        from yoke_core.domain.item_worktree_resolution import (
            resolve_item_id_by_worktree_name,
        )

        try:
            conn = connect_observe_read_db(db_path)
            found = resolve_item_id_by_worktree_name(conn, name)
            conn.close()
        except Exception:
            found = None
        if found is not None:
            return found
    legacy = re.fullmatch(r"YOK-(\d+)", name)
    return int(legacy.group(1)) if legacy else None


__all__ = [
    "compute_tool_call_duration",
    "connect_observe_read_db",
    "repo_root_for_attribution",
    "worktree_path_item_id",
]
