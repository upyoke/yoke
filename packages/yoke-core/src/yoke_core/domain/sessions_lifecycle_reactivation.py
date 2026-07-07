"""Conditional auto-reacquire on session reactivation.

Called from sessions_lifecycle_registry.register_session after the
``ended_at=NULL`` reactivation UPDATE commits. Two outputs:

* the existing ``SessionReactivatedWithReleasedClaims`` advisory
  records *what* prior claims the reactivation surfaced.
* the new conditional auto-reacquire path re-inserts active
  ``work_claims`` rows for the reactivating session when (a) the prior
  release happened with ``release_reason='session_ended'`` inside
  ``session_reactivation_reacquire_window_s``, AND (b) no other
  session currently holds an active claim on the same target.

A receipt event ``SessionReactivationReacquiredClaims`` records the
auto-reacquire outcome (with per-target reacquired vs. conflict).
Honors the conflict semantics — when another session
legitimately holds the item, reacquire falls through to advisory
only and the operator must coordinate or move on.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .runtime_settings import get_seconds
from .sessions_analytics_core import (
    EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
    _emit_session_event,
)
from .sessions_resume_notice import write_pending_resume_notice


DEFAULT_REACQUIRE_WINDOW_S = 300


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _within_window(released_at: Optional[str], window_s: int) -> bool:
    if not released_at:
        return False
    try:
        ts = datetime.fromisoformat(str(released_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    age = (datetime.now(timezone.utc) - ts).total_seconds()
    return 0 <= age <= window_s


def _resolve_reacquire_window_s(override_s: Optional[int] = None) -> int:
    if override_s is not None and override_s > 0:
        return int(override_s)
    return get_seconds(
        "session_reactivation_reacquire_window_s",
        DEFAULT_REACQUIRE_WINDOW_S,
    )


def _target_descriptor(row) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"target_kind": row["target_kind"]}
    if row["item_id"] is not None:
        entry["item_id"] = row["item_id"]
    if row["epic_id"] is not None:
        entry["epic_id"] = row["epic_id"]
    if row["task_num"] is not None:
        entry["task_num"] = row["task_num"]
    if row["process_key"] is not None:
        entry["process_key"] = row["process_key"]
    if row["conflict_group"] is not None:
        entry["conflict_group"] = row["conflict_group"]
    return entry


def _target_key(row) -> Tuple[Any, ...]:
    return (
        row["target_kind"],
        row["item_id"],
        row["epic_id"],
        row["task_num"],
        row["process_key"],
        row["conflict_group"],
    )


def _conflict_holder(
    conn: Any, row,
) -> Tuple[Optional[str], bool]:
    """Return ``(other_holder, self_already_active)`` for this target."""
    target_kind = row["target_kind"]
    sql = (
        "SELECT session_id FROM work_claims "
        "WHERE released_at IS NULL AND target_kind = %s"
    )
    params: List[Any] = [target_kind]
    if target_kind == "item":
        sql += " AND item_id = %s AND session_id <> %s"
        params.extend([row["item_id"], row["session_id"]])
    elif target_kind == "epic_task":
        sql += (
            " AND epic_id = %s AND task_num = %s AND session_id <> %s"
        )
        params.extend([row["epic_id"], row["task_num"], row["session_id"]])
    elif target_kind == "process":
        sql += (
            " AND process_key = %s AND conflict_group = %s AND session_id <> %s"
        )
        params.extend([
            row["process_key"],
            row["conflict_group"],
            row["session_id"],
        ])
    else:  # unrecognised kind — be conservative
        return None, False
    sql += " LIMIT 1"
    hit = conn.execute(sql, tuple(params)).fetchone()
    if hit:
        return hit["session_id"], False

    self_sql = (
        "SELECT 1 FROM work_claims "
        "WHERE released_at IS NULL AND target_kind = %s"
    )
    self_params: List[Any] = [target_kind]
    if target_kind == "item":
        self_sql += " AND item_id = %s AND session_id = %s"
        self_params.extend([row["item_id"], row["session_id"]])
    elif target_kind == "epic_task":
        self_sql += " AND epic_id = %s AND task_num = %s AND session_id = %s"
        self_params.extend([row["epic_id"], row["task_num"], row["session_id"]])
    elif target_kind == "process":
        self_sql += (
            " AND process_key = %s AND conflict_group = %s AND session_id = %s"
        )
        self_params.extend([
            row["process_key"],
            row["conflict_group"],
            row["session_id"],
        ])
    active_self = conn.execute(
        self_sql + " LIMIT 1", tuple(self_params),
    ).fetchone()
    return None, active_self is not None


def _insert_reacquired_claim(
    conn: Any, row, *, now_iso: str,
) -> int:
    """Insert a fresh active work_claims row mirroring the prior target.

    The acquire reason carries over from the prior row — reacquisition
    resumes the same intent, it does not mint a new one.
    """
    from .claim_chain_state import claim_reason_columns_present

    reason_cols = (
        ", reason, reason_intent"
        if claim_reason_columns_present(conn)
        else ""
    )
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, epic_id, task_num, "
        f" process_key, conflict_group, claim_type, claimed_at, last_heartbeat{reason_cols}) "
        "SELECT %s, target_kind, item_id, epic_id, task_num, "
        f"       process_key, conflict_group, 'exclusive', %s, %s{reason_cols} "
        "FROM work_claims WHERE id = %s "
        "RETURNING id",
        (row["session_id"], now_iso, now_iso, row["id"]),
    )
    inserted = cursor.fetchone()
    return int(inserted[0]) if inserted else 0


def auto_reacquire_session_ended_claims(
    conn: Any,
    session_id: str,
    *,
    reacquire_window_s: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Reacquire prior session_ended claims that have no live conflict.

    Returns ``(reacquired, conflicts)``. Both lists carry the original
    target descriptor and, for the reacquired list, the new claim id.
    """
    window = _resolve_reacquire_window_s(reacquire_window_s)
    rows = conn.execute(
        "SELECT id, session_id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group, "
        "released_at FROM work_claims "
        "WHERE session_id = %s AND release_reason = 'session_ended' "
        "  AND released_at IS NOT NULL "
        "ORDER BY id DESC",
        (session_id,),
    ).fetchall()
    if not rows:
        return [], []

    reacquired: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    seen_targets: set[Tuple[Any, ...]] = set()
    now_iso = _now_iso()
    for row in rows:
        target_key = _target_key(row)
        if target_key in seen_targets:
            continue
        seen_targets.add(target_key)
        if not _within_window(row["released_at"], window):
            continue
        target = _target_descriptor(row)
        holder, self_already_active = _conflict_holder(conn, row)
        if self_already_active:
            continue
        if holder is not None:
            conflicts.append({**target, "holder_session_id": holder})
            continue
        new_id = _insert_reacquired_claim(conn, row, now_iso=now_iso)
        reacquired.append({**target, "new_claim_id": new_id})

    if reacquired:
        conn.commit()
    return reacquired, conflicts


def emit_reactivated_with_released_claims(
    conn: Any,
    session_id: str,
    *,
    reacquire_window_s: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Emit the advisory event AND drive conditional auto-reacquire.

    Returns the list of prior released-claim descriptors. The advisory
    is preserved verbatim for doctrine continuity; the new
    auto-reacquire receipt event is emitted in addition when at least
    one claim was reacquired OR at least one conflict was observed.
    """
    rows = conn.execute(
        "SELECT id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group "
        "FROM work_claims "
        "WHERE session_id = %s AND release_reason = 'session_ended' "
        "  AND released_at IS NOT NULL "
        "ORDER BY id DESC",
        (session_id,),
    ).fetchall()

    if not rows:
        return []

    released_claims: List[Dict[str, Any]] = [_target_descriptor(r) for r in rows]
    _emit_session_event(
        EVENT_SESSION_REACTIVATED_WITH_RELEASED_CLAIMS,
        session_id=session_id,
        context={
            "released_claim_count": len(released_claims),
            "released_claims": released_claims,
        },
    )

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        conn, session_id, reacquire_window_s=reacquire_window_s,
    )
    if reacquired or conflicts:
        from .scheduler_events import emit_session_reactivation_reacquired_claims

        emit_session_reactivation_reacquired_claims(
            session_id=session_id,
            reacquired_count=len(reacquired),
            conflict_count=len(conflicts),
            claim_details=[
                *({"outcome": "reacquired", **r} for r in reacquired),
                *({"outcome": "conflict", **c} for c in conflicts),
            ],
        )

    from .sessions_lifecycle_resumption_emit import emit_session_resumed

    emit_session_resumed(
        session_id=session_id,
        released_claims=released_claims,
        reacquired_claims=reacquired,
        conflicts=conflicts,
    )

    # Arm the slim "SESSION RESUMED" block: the render-once state machine
    # is the pending_resume_notice column — written here, cleared by the
    # hook-runner render (sessions_resume_block.render_and_mark).
    write_pending_resume_notice(
        conn,
        session_id,
        released_claims=released_claims,
        reacquired_count=len(reacquired),
        conflict_count=len(conflicts),
    )

    return released_claims


__all__ = [
    "DEFAULT_REACQUIRE_WINDOW_S",
    "auto_reacquire_session_ended_claims",
    "emit_reactivated_with_released_claims",
]
