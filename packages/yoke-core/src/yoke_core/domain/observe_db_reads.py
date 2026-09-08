"""Read-side DB helpers for observe telemetry attribution."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from yoke_core.domain import db_backend
from yoke_core.domain.observe_db import normalize_observe_db_path
from yoke_core.domain.observe_timing import (
    CapturedTimestamp,
    ElapsedMeasurement,
    TIMING_UNKNOWN_LOOKUP_FAILED,
    TIMING_UNKNOWN_NO_CALL_IDENTITY,
    TIMING_UNKNOWN_NO_CAPTURED_END,
    TIMING_UNKNOWN_NO_RECORDED_START,
    measure_elapsed,
    start_endpoint_is_synthesized,
)


def connect_observe_read_db(db_path: Optional[str]):
    """Connect for observe read-side attribution.

    The path is a routing token for the backend factory, not a raw SQLite file
    authority. Live hooks and Postgres tests both resolve through the selected
    Yoke backend; callers stay fail-open by catching connection/query errors.
    """
    normalized = normalize_observe_db_path(db_path)

    from yoke_core.domain.db_helpers import connect

    return connect(normalized)


def measure_tool_call_duration(
    db_path: Optional[str],
    *,
    session_id: str,
    tool_use_id: str,
    completed_at: CapturedTimestamp,
) -> ElapsedMeasurement:
    """Measure one tool call between its two captured endpoints.

    The start is the ``session_tool_calls`` row the call's own PreToolUse
    observation opened; the end is ``completed_at``, the instant the caller
    captured the call closing. Both are captured at the tool boundary, so
    the interval survives however long telemetry took to arrive.

    A row whose start was synthesized by a completion that arrived before
    the opening observation carries no captured start at all, so it reports
    the same missing-start reason an absent row does rather than the
    zero-length call its two identical endpoints would otherwise measure.
    Once the genuine start lands and supersedes the placeholder, this read
    converges on the real interval — whichever order the two observations
    arrived in.

    The lookup is scoped by ``(session_id, tool_use_id)`` — the row's own
    unique identity — because a tool-use id is only unique within its
    session. Read failures stay fail-open: this returns a named unknown so
    the hook never blocks a tool on telemetry.
    """
    if not session_id or not tool_use_id:
        return ElapsedMeasurement(None, TIMING_UNKNOWN_NO_CALL_IDENTITY)
    if completed_at is None or (
        isinstance(completed_at, str) and not completed_at.strip()
    ):
        return ElapsedMeasurement(None, TIMING_UNKNOWN_NO_CAPTURED_END)
    try:
        conn = connect_observe_read_db(db_path)
        try:
            marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
            row = conn.execute(
                "SELECT started_at, completed_at FROM session_tool_calls "
                f"WHERE session_id = {marker} AND tool_use_id = {marker}",
                (session_id, tool_use_id),
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return ElapsedMeasurement(None, TIMING_UNKNOWN_LOOKUP_FAILED)
    if row is None or start_endpoint_is_synthesized(row[0], row[1]):
        return ElapsedMeasurement(None, TIMING_UNKNOWN_NO_RECORDED_START)
    return measure_elapsed(row[0], completed_at)


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
    "connect_observe_read_db",
    "measure_tool_call_duration",
    "repo_root_for_attribution",
    "worktree_path_item_id",
]
