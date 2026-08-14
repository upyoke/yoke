"""Event emission for the lane-main-write guard."""

from __future__ import annotations

import json
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_core.domain.session_staleness import activity_is_stale


def _emit(
    name: str,
    outcome: str,
    context: dict,
    *,
    session_id: str = "",
    item_id: Optional[int] = None,
    severity: str = "WARN",
) -> None:
    try:
        from yoke_core.domain import emit_event as emit_event_cli

        parser = emit_event_cli.build_parser()
        args = parser.parse_args(
            [
                "--name",
                name,
                "--kind",
                "lifecycle",
                "--type",
                "session_cwd",
                "--source-type",
                "hook",
                "--severity",
                severity,
                "--outcome",
                outcome,
                "--context",
                json.dumps(context, separators=(",", ":")),
                *(
                    ["--session-id", session_id]
                    if session_id
                    else []
                ),
                *(
                    ["--item-id", str(int(item_id))]
                    if item_id is not None
                    else []
                ),
            ]
        )
        emit_event_cli.emit(args)
    except Exception:
        pass


def emit_escape_used(
    *,
    session_id: str,
    attempted_path: str,
    lane_path: str,
    item_id: int,
) -> None:
    """Record deliberate main-targeted work while a lane is held."""
    _emit(
        name="LaneMainWriteEscapeUsed",
        outcome="escape_used",
        context={
            "attempted_path": attempted_path,
            "lane_path": lane_path,
            "item_id": int(item_id),
            "escape_token": "# lint:allow-lane-main-write",
        },
        session_id=session_id,
        item_id=int(item_id),
        severity="INFO",
    )


def emit_denied(
    *,
    session_id: str,
    attempted_path: str,
    lane_path: str,
    lane_equivalent: str,
    item_id: int,
    mode: str,
    suppression_attempted: bool,
) -> None:
    outcome = "suppression_attempted" if suppression_attempted else "blocked"
    _emit(
        name="LaneMainWriteDenied",
        outcome=outcome,
        context={
            "attempted_path": attempted_path,
            "lane_path": lane_path,
            "lane_equivalent": lane_equivalent,
            "item_id": int(item_id),
            "mode": mode,
            "failure_class": "lane_main_write",
        },
        session_id=session_id,
        item_id=int(item_id),
    )


def emit_stranded_lane_advisory(
    *,
    session_id: str,
    lane_path: str,
    item_id: int,
    item_label: str,
) -> None:
    """Record that a held lane claim has no on-disk worktree (do not deny)."""
    _emit(
        name="LaneMainWriteStrandedLane",
        outcome="advisory",
        context={
            "lane_path": lane_path,
            "item_id": int(item_id),
            "item_label": item_label,
            "failure_class": "stranded_lane",
        },
        session_id=session_id,
        item_id=int(item_id),
        severity="INFO",
    )


def claim_heartbeat_is_stale(
    conn: Any, session_id: str, claim: ClaimedWorktree,
) -> bool:
    """True when the matching work claim's heartbeat is past the stale TTL."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        if claim.task_num is None:
            row = conn.execute(
                "SELECT last_heartbeat FROM work_claims "
                f"WHERE session_id = {marker} AND released_at IS NULL "
                f"AND target_kind = 'item' AND item_id = {marker}",
                (session_id, int(claim.item_id)),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT last_heartbeat FROM work_claims "
                f"WHERE session_id = {marker} AND released_at IS NULL "
                f"AND target_kind = 'epic_task' AND epic_id = {marker} "
                f"AND task_num = {marker}",
                (session_id, int(claim.item_id), int(claim.task_num)),
            ).fetchone()
    except db_backend.operational_error_types(conn):
        return False
    if row is None:
        return False
    value = row["last_heartbeat"] if hasattr(row, "keys") else row[0]
    return activity_is_stale(value, executor=None)


def stranded_advisory_already_recorded(
    conn: Any, *, session_id: str, item_id: int,
) -> bool:
    """True when this session+item already has a stranded-lane advisory."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT 1 FROM events "
            f"WHERE event_name = {marker} AND session_id = {marker} "
            f"AND item_id = {marker} LIMIT 1",
            ("LaneMainWriteStrandedLane", session_id, str(int(item_id))),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        return False
    return row is not None


__all__ = [
    "claim_heartbeat_is_stale",
    "emit_denied",
    "emit_escape_used",
    "emit_stranded_lane_advisory",
    "stranded_advisory_already_recorded",
]
