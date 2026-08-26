"""Transactional claim reacquisition for an active resumed session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .runtime_settings import get_seconds
from .sessions_analytics import SessionError
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from .workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)
from .work_claim_targets import from_row as work_claim_target_from_row
from .work_claim_targets import TARGET_KIND_STEERING_SCOPE

DEFAULT_REACQUIRE_WINDOW_S = 300
REACTIVATION_RELEASE_REASONS = ("session_ended", "reclaimed")
_REACTIVATION_REASON_SQL = (
    "(" + ", ".join(f"'{reason}'" for reason in REACTIVATION_RELEASE_REASONS) + ")"
)


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


def target_descriptor(row: Any) -> Dict[str, Any]:
    """Render the stable event descriptor for one claim target row."""
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
    if row["target_kind"] == TARGET_KIND_STEERING_SCOPE:
        target = work_claim_target_from_row(dict(row))
        entry["steering_project_id"] = target.steering_project_id
        entry["steering_strategy_doc_slugs"] = list(
            target.steering_strategy_doc_slugs or ()
        )
    return entry


def _target_key(row: Any) -> Tuple[Any, ...]:
    return (
        row["target_kind"],
        row["item_id"],
        row["epic_id"],
        row["task_num"],
        row["process_key"],
        row["conflict_group"],
        row["steering_project_id"],
        row["steering_strategy_doc_slugs"],
    )


def _conflict_holder(conn: Any, row: Any) -> Tuple[Optional[str], bool]:
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
        sql += " AND epic_id = %s AND task_num = %s AND session_id <> %s"
        params.extend([row["epic_id"], row["task_num"], row["session_id"]])
    elif target_kind == "process":
        sql += " AND process_key = %s AND conflict_group = %s AND session_id <> %s"
        params.extend(
            [
                row["process_key"],
                row["conflict_group"],
                row["session_id"],
            ]
        )
    elif target_kind == TARGET_KIND_STEERING_SCOPE:
        from .steering_scope_claims import scopes_intersect

        target = work_claim_target_from_row(dict(row))
        candidates = conn.execute(
            "SELECT session_id, steering_project_id, "
            "steering_strategy_doc_slugs FROM work_claims "
            "WHERE released_at IS NULL AND target_kind = 'steering_scope' "
            "AND steering_project_id = %s ORDER BY claimed_at, id",
            (target.steering_project_id,),
        ).fetchall()
        for candidate in candidates:
            candidate_target = work_claim_target_from_row(
                {
                    "target_kind": TARGET_KIND_STEERING_SCOPE,
                    "steering_project_id": candidate["steering_project_id"],
                    "steering_strategy_doc_slugs": candidate[
                        "steering_strategy_doc_slugs"
                    ],
                }
            )
            if not scopes_intersect(
                target.steering_strategy_doc_slugs or (),
                candidate_target.steering_strategy_doc_slugs or (),
            ):
                continue
            if (
                candidate["session_id"] == row["session_id"]
                and candidate_target == target
            ):
                return None, True
            return str(candidate["session_id"]), False
        return None, False
    else:
        return None, False
    hit = conn.execute(sql + " LIMIT 1", tuple(params)).fetchone()
    if hit:
        return hit["session_id"], False

    self_sql = (
        "SELECT 1 FROM work_claims WHERE released_at IS NULL AND target_kind = %s"
    )
    self_params: List[Any] = [target_kind]
    if target_kind == "item":
        self_sql += " AND item_id = %s AND session_id = %s"
        self_params.extend([row["item_id"], row["session_id"]])
    elif target_kind == "epic_task":
        self_sql += " AND epic_id = %s AND task_num = %s AND session_id = %s"
        self_params.extend([row["epic_id"], row["task_num"], row["session_id"]])
    elif target_kind == "process":
        self_sql += " AND process_key = %s AND conflict_group = %s AND session_id = %s"
        self_params.extend(
            [
                row["process_key"],
                row["conflict_group"],
                row["session_id"],
            ]
        )
    else:
        return None, False
    active_self = conn.execute(
        self_sql + " LIMIT 1",
        tuple(self_params),
    ).fetchone()
    return None, active_self is not None


def _insert_reacquired_claim(conn: Any, row: Any, *, now_iso: str) -> int:
    """Insert a fresh active claim mirroring the prior target and intent."""
    from .claim_chain_state import claim_reason_columns_present

    reason_cols = (
        ", reason, reason_intent" if claim_reason_columns_present(conn) else ""
    )
    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, epic_id, task_num, "
        " process_key, conflict_group, steering_project_id, "
        " steering_strategy_doc_slugs, owner_kind, owner_item_id, "
        " owner_session_id, owner_work_claim_id, registered_by_actor_id, "
        " registered_by_session_id, claim_type, claimed_at, last_heartbeat"
        f"{reason_cols}) "
        "SELECT %s, target_kind, item_id, epic_id, task_num, "
        "       process_key, conflict_group, steering_project_id, "
        "       steering_strategy_doc_slugs, owner_kind, owner_item_id, "
        "       owner_session_id, owner_work_claim_id, registered_by_actor_id, "
        "       registered_by_session_id, 'exclusive', %s, %s"
        f"{reason_cols} "
        "FROM work_claims WHERE id = %s "
        "RETURNING id",
        (row["session_id"], now_iso, now_iso, row["id"]),
    )
    inserted = cursor.fetchone()
    return int(inserted[0]) if inserted else 0


def _released_claim_rows(conn: Any, session_id: str) -> list[Any]:
    return conn.execute(
        "SELECT id, session_id, target_kind, item_id, epic_id, task_num, "
        "process_key, conflict_group, steering_project_id, "
        "steering_strategy_doc_slugs, owner_kind, owner_item_id, "
        "owner_session_id, owner_work_claim_id, registered_by_actor_id, "
        "registered_by_session_id, released_at, release_reason FROM work_claims "
        "WHERE session_id = %s AND release_reason IN "
        f"{_REACTIVATION_REASON_SQL} "
        "AND released_at IS NOT NULL ORDER BY id DESC",
        (session_id,),
    ).fetchall()


def released_claim_rows_for_reactivation(conn: Any, session_id: str) -> list[Any]:
    """Return prior session-ended or reclaimed claims for a resumed session."""
    return _released_claim_rows(conn, session_id)


@rollback_workflow_binding_write_errors
def auto_reacquire_session_ended_claims(
    conn: Any,
    session_id: str,
    *,
    reacquire_window_s: Optional[int] = None,
    commit: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Reacquire recent session-ended or reclaimed claims that have no live conflict."""
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
        )

    rows = _released_claim_rows(conn, session_id)
    if not rows:
        if commit:
            conn.commit()
        return [], []

    from .steering_scope_claims import lock_project_scope

    for project_id in sorted(
        {
            int(row["steering_project_id"])
            for row in rows
            if row["target_kind"] == TARGET_KIND_STEERING_SCOPE
        }
    ):
        lock_project_scope(conn, project_id)
    lock_work_claims_workflow_bindings(
        conn,
        (int(row["id"]) for row in rows),
    )
    rows = _released_claim_rows(conn, session_id)
    window = _resolve_reacquire_window_s(reacquire_window_s)
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
        target = target_descriptor(row)
        try:
            validate_work_claim_target(
                conn,
                work_claim_target_from_row(dict(row)),
            )
        except WorkflowItemBindingError as exc:
            conflicts.append({**target, "invalid_target_reason": str(exc)})
            continue
        holder, self_already_active = _conflict_holder(conn, row)
        if self_already_active:
            continue
        if holder is not None:
            conflicts.append({**target, "holder_session_id": holder})
            continue
        new_id = _insert_reacquired_claim(conn, row, now_iso=now_iso)
        reacquired.append({**target, "new_claim_id": new_id})

    if commit:
        conn.commit()
    return reacquired, conflicts


__all__ = [
    "DEFAULT_REACQUIRE_WINDOW_S",
    "REACTIVATION_RELEASE_REASONS",
    "auto_reacquire_session_ended_claims",
    "released_claim_rows_for_reactivation",
    "target_descriptor",
]
