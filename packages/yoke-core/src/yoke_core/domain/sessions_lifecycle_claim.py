"""Typed session work-claim acquisition and direct claim release."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import db_backend
from .sessions_analytics import SessionError
from .sessions_claim_lifecycle_lock import lock_session_rows_for_claim_lifecycle
from .sessions_ended_recovery import session_ended_message
from .sessions_lifecycle_claim_events import emit_work_claimed
from .sessions_lifecycle_registry import _get_claim
from .sessions_queries import _now_iso, normalize_claim_item_id
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    WorkClaimTarget,
    make_item_target,
)
from . import workflow_item_binding_lock as binding_lock
from .workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _self_claim_clause(target: WorkClaimTarget, p: str) -> tuple[str, list[Any]]:
    """SQL fragment + params matching an active claim by THIS session for ``target``."""
    if target.kind == TARGET_KIND_ITEM:
        return (
            f"target_kind='item' AND item_id = {p}",
            [target.item_id],
        )
    if target.kind == TARGET_KIND_EPIC_TASK:
        return (
            f"target_kind='epic_task' AND epic_id = {p} AND task_num = {p}",
            [target.epic_id, target.task_num],
        )
    return (
        f"target_kind='process' AND process_key = {p}",
        [target.process_key],
    )


def _conflict_clause(target: WorkClaimTarget, p: str) -> tuple[str, list[Any]]:
    """SQL fragment + params matching any active conflicting claim by another session."""
    if target.kind == TARGET_KIND_ITEM:
        return (
            f"target_kind='item' AND item_id = {p}",
            [target.item_id],
        )
    if target.kind == TARGET_KIND_EPIC_TASK:
        return (
            f"target_kind='epic_task' AND epic_id = {p} AND task_num = {p}",
            [target.epic_id, target.task_num],
        )
    # Process-target conflicts share the conflict_group; this is what makes
    # STRATEGIZE and FEED on the same project mutually exclusive.
    return (
        f"target_kind='process' AND conflict_group = {p}",
        [target.conflict_group],
    )


def _insert_typed_claim(
    conn: Any,
    session_id: str,
    target: WorkClaimTarget,
    now: str,
) -> int:
    """Atomic INSERT-with-conflict-check guard against late-racing claims.

    The INSERT is gated by ``WHERE NOT EXISTS`` against the same conflict
    clause the pre-check used; ``cursor.rowcount == 0`` means the race
    lost — the caller raises ALREADY_CLAIMED with the winning session id.
    Storage-level defense: the partial unique indexes
    ``idx_work_claims_active_item`` / ``idx_work_claims_active_epic_task``
    (active rows per target kind) make ``IntegrityError`` the
    authoritative late-racer signal; the caller maps it to the same
    ALREADY_CLAIMED semantics as the rowcount path.
    """
    p = _p(conn)
    conflict_clause, conflict_params = _conflict_clause(target, p)
    cursor = conn.execute(
        f"""INSERT INTO work_claims
           (session_id, target_kind, item_id, epic_id, task_num,
            process_key, conflict_group, claim_type,
            claimed_at, last_heartbeat, released_at, release_reason)
           SELECT {p}, {p}, {p}, {p}, {p}, {p}, {p}, 'exclusive', {p}, {p}, NULL, NULL
           WHERE NOT EXISTS (
               SELECT 1 FROM work_claims
               WHERE {conflict_clause}
                 AND released_at IS NULL
                 AND session_id <> {p}
           )
           RETURNING id""",
        (
            session_id,
            target.kind,
            target.item_id,
            target.epic_id,
            target.task_num,
            target.process_key,
            target.conflict_group,
            now,
            now,
            *conflict_params,
            session_id,
        ),
    )
    row = cursor.fetchone()
    if row is None:
        return 0
    return int(row[0])


def _resolve_active_holder(
    conn: Any,
    target: WorkClaimTarget,
    session_id: str,
) -> str:
    """Re-resolve the active holder for ``target`` excluding ``session_id``.

    Used after both the rowcount-zero path and the IntegrityError path
    so the ALREADY_CLAIMED message names the winning session.
    """
    p = _p(conn)
    conflict_clause, conflict_params = _conflict_clause(target, p)
    winner = conn.execute(
        f"SELECT session_id FROM work_claims "
        f"WHERE {conflict_clause} AND released_at IS NULL "
        f"AND session_id <> {p} LIMIT 1",
        [*conflict_params, session_id],
    ).fetchone()
    if winner is None:
        return "unknown"
    return winner["session_id"]


@binding_lock.rollback_workflow_binding_write_errors
def claim_work(
    conn: Any,
    *,
    session_id: str,
    target: Optional[WorkClaimTarget] = None,
    item_id: Optional[str] = None,
    claim_type: str = "exclusive",
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Acquire a typed work claim for ``session_id``.

    Pass either ``target`` (preferred — typed path) or ``item_id``
    (item-target convenience). ``claim_type`` accepts only ``"exclusive"``.
    ``reason`` lands verbatim on ``work_claims.reason`` (canonical tag
    classified into ``reason_intent``) and echoes on ``WorkClaimed``.
    """
    from yoke_core.domain.sessions import clean_stale_harness_sessions
    from .sessions_render import set_current_item

    if claim_type != "exclusive":
        raise SessionError(
            "INVALID_CLAIM",
            "claim_type must be 'exclusive'.",
        )

    if target is None:
        if item_id is None:
            raise SessionError(
                "INVALID_CLAIM",
                "Must specify target=WorkClaimTarget(...) or item_id=...",
            )
        target = make_item_target(int(normalize_claim_item_id(item_id)))
    if target.steering_project_id is not None:
        raise SessionError("INVALID_CLAIM", "Steering scopes require the project-serialized steering_scope_claims.acquire path.")

    now = _now_iso()
    p = _p(conn)
    self_clause, self_params = _self_claim_clause(target, p)
    conflict_clause, conflict_params = _conflict_clause(target, p)

    sess_row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    if sess_row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if sess_row["ended_at"] is not None:
        raise SessionError(
            "SESSION_ENDED",
            session_ended_message(conn, session_id),
        )

    conflict = conn.execute(
        f"SELECT session_id FROM work_claims "
        f"WHERE {conflict_clause} AND released_at IS NULL AND session_id <> {p} "
        f"LIMIT 1",
        [*conflict_params, session_id],
    ).fetchone()

    if conflict is not None:
        try:
            clean_stale_harness_sessions(conn)
        except Exception:
            if db_backend.connection_is_postgres(conn):
                # A swallowed psycopg error leaves the transaction aborted.
                # Roll back before the follow-up conflict read reuses it.
                try:
                    conn.rollback()
                except Exception:
                    pass
            pass

    # The preflight stale-cleanup transaction may touch claim rows. Finish it
    # before entering the canonical session -> item -> claim lock order used
    # by the acquisition transaction.
    conn.commit()
    session_rows = lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    if session_id not in session_rows:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if session_rows[session_id] is not None:
        raise SessionError(
            "SESSION_ENDED",
            session_ended_message(conn, session_id),
        )

    binding_lock.lock_work_claim_target_workflow_binding(conn, target)
    try:
        validate_work_claim_target(conn, target)
    except WorkflowItemBindingError as exc:
        raise SessionError("INVALID_CLAIM", str(exc)) from exc
    if target.kind == TARGET_KIND_ITEM:
        from yoke_core.domain.strategy_doc_claim_exclusion import (
            document_lock_refusal,
        )

        locked = document_lock_refusal(conn, int(target.item_id))
        if locked is not None:
            raise SessionError("DOCUMENT_LOCKED", locked)
    dup = conn.execute(
        f"SELECT id FROM work_claims "
        f"WHERE session_id = {p} AND {self_clause} AND released_at IS NULL "
        f"ORDER BY claimed_at DESC, id DESC LIMIT 1",
        [session_id, *self_params],
    ).fetchone()
    if dup is not None:
        claim_id = int(dup["id"] if hasattr(dup, "keys") else dup[0])
        conn.commit()
        row = _get_claim(conn, claim_id)
        # Acquisition registers no linked path claims (pure process lock).
        row["linked_path_claim_ids"] = []
        return row

    conflict = conn.execute(
        f"SELECT session_id FROM work_claims "
        f"WHERE {conflict_clause} AND released_at IS NULL AND session_id <> {p} "
        f"LIMIT 1",
        [*conflict_params, session_id],
    ).fetchone()

    if conflict is not None:
        raise SessionError(
            "ALREADY_CLAIMED",
            f"Work unit already has an active exclusive claim by session "
            f"'{conflict['session_id']}'.",
        )
    integrity_errors = db_backend.integrity_error_types(conn)
    try:
        claim_id = _insert_typed_claim(conn, session_id, target, now)
    except integrity_errors:
        # Storage-level defense: a concurrent writer's row landed
        # between our pre-check and INSERT and tripped the partial
        # unique index. Preserve ALREADY_CLAIMED semantics.
        if db_backend.connection_is_postgres(conn):
            conn.rollback()
        winner_id = _resolve_active_holder(conn, target, session_id)
        raise SessionError(
            "ALREADY_CLAIMED",
            f"Work unit already has an active exclusive claim by session "
            f"'{winner_id}'.",
        ) from None
    if claim_id == 0:
        # Lost the race — re-resolve the holder for the error message.
        winner_id = _resolve_active_holder(conn, target, session_id)
        raise SessionError(
            "ALREADY_CLAIMED",
            f"Work unit already has an active exclusive claim by session "
            f"'{winner_id}'.",
        )
    if target.kind == TARGET_KIND_ITEM:
        set_current_item(
            conn,
            session_id,
            str(target.item_id),
            commit=False,
        )
    # Acquire reason is first-class claim state.
    from yoke_core.domain.claim_chain_state import (
        record_claim_reason,
        touch_epic_task_activity,
    )

    record_claim_reason(conn, claim_id=claim_id, reason=reason)
    # Claim acquire is real item activity for board freshness.
    _activity_target = (
        target.item_id if target.kind == TARGET_KIND_ITEM else target.epic_id
    )
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity

        touch_item_activity(conn, item_id=_activity_target)
    if target.kind == TARGET_KIND_EPIC_TASK:
        # An epic-task acquire is task activity for chain-head freshness.
        touch_epic_task_activity(
            conn,
            epic_id=target.epic_id,
            task_num=target.task_num,
            at=now,
        )
    conn.commit()
    emit_work_claimed(
        session_id,
        claim_id,
        target,
        linked_path_claim_ids=[],
        reason=reason,
    )
    row = _get_claim(conn, claim_id)
    # Acquisition registers no linked path claims (pure process lock).
    row["linked_path_claim_ids"] = []
    return row


def release_claim(
    conn: Any,
    claim_id: int,
    reason: str = "released",
) -> Dict[str, Any]:
    """Release a claim; canonicalize reason → schema-enum for storage.

    Delegates to ``sessions_lifecycle_claim_release.release_claim_by_id``
    (sibling module) so the by-claim-id path matches
    the session-scoped path in cascading linked process path claims.
    """
    from .sessions_lifecycle_claim_release import release_claim_by_id

    return release_claim_by_id(conn, claim_id, reason)
