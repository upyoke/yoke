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

    The lane name resolves through the recorded lane or its public ref in
    any project. Without a control-plane read there is no attribution: the
    number in the name is a project sequence, not ``items.id``.
    """
    import re

    match = re.search(r"\.worktrees/([^/]+)/", file_path or "")
    if not match or not db_path:
        return None
    from yoke_core.domain.item_worktree_resolution import item_id_for_lane_name

    try:
        conn = connect_observe_read_db(db_path)
        try:
            return item_id_for_lane_name(conn, match.group(1))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - attribution is best-effort telemetry
        return None


def public_ref_item_ids(command: str, db_path: Optional[str]) -> set[str]:
    """Return the ``items.id`` of every public ref (any prefix) in COMMAND.

    Tokens that name no item, such as ``SHA-256``, resolve to nothing. Ids
    come back as strings to match the other explicit-ref sets.
    """
    import re

    from yoke_contracts.public_ref import parse_public_item_ref

    tokens = {
        token
        for token in re.findall(r"\b[A-Z][A-Z0-9]*-\d+\b", command or "")
        if parse_public_item_ref(token)[0] is not None
    }
    if not tokens or not db_path:
        return set()
    from yoke_core.domain.item_ref_resolution import resolve_item_ref_or_none

    found: set[str] = set()
    try:
        conn = connect_observe_read_db(db_path)
        try:
            for token in tokens:
                item_id = resolve_item_ref_or_none(conn, token)
                if item_id is not None:
                    found.add(str(item_id))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - attribution is best-effort telemetry
        return set()
    return found


__all__ = [
    "connect_observe_read_db",
    "measure_tool_call_duration",
    "public_ref_item_ids",
    "repo_root_for_attribution",
    "worktree_path_item_id",
]
