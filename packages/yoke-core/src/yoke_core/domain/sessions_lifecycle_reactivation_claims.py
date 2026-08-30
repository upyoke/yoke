"""Transactional claim reacquisition for an active resumed session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG

from .runtime_settings import get_seconds
from .sessions_analytics import SessionError
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_render_attribution import (
    focus_fallback_item_id,
    set_current_item,
)
from .workflow_item_binding_lock import (
    lock_work_claims_workflow_bindings,
    rollback_workflow_binding_write_errors,
)
from .workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)
from .work_claim_targets import (
    TARGET_KIND_STEERING,
    conflict_match_clause,
    exact_match_clause,
    from_row as work_claim_target_from_row,
)

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
    target = work_claim_target_from_row(dict(row))
    return {"target_kind": target.kind, "scope": dict(target.scope)}


def _target_key(row: Any) -> Tuple[Any, ...]:
    target = work_claim_target_from_row(dict(row))
    return (target.kind, target.scope_json())


def _conflict_holder(conn: Any, row: Any) -> Tuple[Optional[str], bool]:
    """Return ``(other_holder, self_already_active)`` for this target."""
    target = work_claim_target_from_row(dict(row))
    conflict_sql, conflict_params = conflict_match_clause(conn, target)
    hit = conn.execute(
        "SELECT session_id FROM work_claims WHERE released_at IS NULL "
        f"AND {conflict_sql} AND session_id <> %s LIMIT 1",
        (*conflict_params, row["session_id"]),
    ).fetchone()
    if hit:
        return hit["session_id"], False
    self_sql, self_params = exact_match_clause(conn, target)
    active_self = conn.execute(
        "SELECT 1 FROM work_claims WHERE released_at IS NULL "
        f"AND {self_sql} AND session_id = %s LIMIT 1",
        (*self_params, row["session_id"]),
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
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat"
        f"{reason_cols}) "
        "SELECT %s, target_kind, scope, 'exclusive', %s, %s"
        f"{reason_cols} "
        "FROM work_claims WHERE id = %s "
        "RETURNING id",
        (row["session_id"], now_iso, now_iso, row["id"]),
    )
    inserted = cursor.fetchone()
    return int(inserted[0]) if inserted else 0


def _released_claim_rows(conn: Any, session_id: str) -> list[Any]:
    return conn.execute(
        "SELECT id, session_id, target_kind, scope, released_at, release_reason "
        "FROM work_claims "
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

    from .steering_claims import lock_project

    for project_id in sorted(
        {
            int(work_claim_target_from_row(dict(row)).project_id)
            for row in rows
            if row["target_kind"] == TARGET_KIND_STEERING
        }
    ):
        lock_project(conn, project_id)
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
        if row["target_kind"] == TARGET_KIND_STEERING:
            from .strategy_doc_steering_pair import (
                paired_document_slug_for_history,
            )
            from .strategy_docs import StrategyDocMissingError
            from .strategy_execution import (
                StrategyExecutionError,
                acquire_session_doc_claim,
            )

            doc_slug = (
                paired_document_slug_for_history(conn, int(row["id"]))
                or DEFAULT_STEERING_DOC_SLUG
            )
            try:
                acquire_session_doc_claim(
                    conn,
                    project_id=int(work_claim_target_from_row(dict(row)).project_id),
                    slug=doc_slug,
                    session_id=session_id,
                    actor_id=None,
                    reason="session reactivated",
                    commit=False,
                )
            except (StrategyExecutionError, StrategyDocMissingError) as exc:
                conn.execute("DELETE FROM work_claims WHERE id = %s", (new_id,))
                conflicts.append(
                    {
                        **target,
                        "strategy_doc_slug": doc_slug,
                        "document_claim_refusal": str(exc),
                    }
                )
                continue
        reacquired.append({**target, "new_claim_id": new_id})

    if reacquired:
        _restore_focus_for_reacquired_claims(conn, session_id)
    if commit:
        conn.commit()
    return reacquired, conflicts


def _restore_focus_for_reacquired_claims(conn: Any, session_id: str) -> None:
    """Point focus back at claimed work the resumed episode still holds.

    Ending the session archived ``current_item_id`` to ``recent_item_id``,
    so a session whose item claims came back would otherwise read as
    holding work while attending nothing. Focus is claim-derived, so it
    is restored from the newest active item claim and never invented: a
    session that reacquired only epic-task, process, or steering claims
    keeps an empty slot, and one that already refocused keeps that.
    """
    row = conn.execute(
        "SELECT current_item_id FROM harness_sessions WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    if row is None or row["current_item_id"] is not None:
        return
    item_id = focus_fallback_item_id(conn, session_id)
    if item_id is None:
        return
    set_current_item(conn, session_id, item_id, commit=False)


__all__ = [
    "DEFAULT_REACQUIRE_WINDOW_S",
    "REACTIVATION_RELEASE_REASONS",
    "auto_reacquire_session_ended_claims",
    "released_claim_rows_for_reactivation",
    "target_descriptor",
]
