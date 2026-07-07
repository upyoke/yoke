"""Session work-claim acquisition and direct claim release.

Typed-target schema: every active claim populates exactly one of
``(target_kind='item', item_id)``, ``(target_kind='epic_task', epic_id,
task_num)``, or ``(target_kind='process', process_key, conflict_group)``
— CHECK-enforced. This module owns the typed acquire path + a direct
release helper."""

from __future__ import annotations

from typing import Any, Dict, Optional

from . import db_backend
from . import sessions_analytics as _sa
from .sessions_analytics import EVENT_WORK_CLAIMED, EVENT_WORK_RELEASED, SessionError
from .sessions_lifecycle_registry import _get_claim
from .sessions_queries import _now_iso, normalize_claim_item_id
from .work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    make_item_target,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _emit_work_claimed(
    session_id: str,
    claim_id: int,
    target: WorkClaimTarget,
    *,
    linked_path_claim_ids: Optional[list[int]] = None,
    reason: Optional[str] = None,
) -> None:
    context: Dict[str, Any] = {
        "claim_id": claim_id,
        "target_kind": target.kind,
        "claim_type": "exclusive",
    }
    if reason:
        context["claim_reason_intent"] = reason
    item_id_for_event: Optional[str] = None
    task_num_for_event: Optional[int] = None
    if target.kind == TARGET_KIND_ITEM:
        context["item_id"] = str(target.item_id)
        item_id_for_event = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        context["epic_id"] = target.epic_id
        context["task_num"] = target.task_num
        item_id_for_event = str(target.epic_id)
        task_num_for_event = target.task_num
    else:
        context["process_key"] = target.process_key
        context["conflict_group"] = target.conflict_group
        context["linked_path_claim_ids"] = list(linked_path_claim_ids or [])
    _sa._emit_session_event(
        EVENT_WORK_CLAIMED,
        session_id=session_id,
        item_id=item_id_for_event,
        task_num=task_num_for_event,
        context=context,
    )


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

    now = _now_iso()
    p = _p(conn)
    self_clause, self_params = _self_claim_clause(target, p)
    conflict_clause, conflict_params = _conflict_clause(target, p)

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

    sess_row = conn.execute(
        f"SELECT ended_at FROM harness_sessions WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    if sess_row is None:
        raise SessionError("NOT_FOUND", f"Session '{session_id}' not found.")
    if sess_row["ended_at"] is not None:
        raise SessionError(
            "SESSION_ENDED",
            f"Session '{session_id}' has already ended.",
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
        set_current_item(conn, session_id, str(target.item_id))
    # Acquire reason is first-class claim state.
    from yoke_core.domain.claim_chain_state import record_claim_reason, touch_epic_task_activity
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
            conn, epic_id=target.epic_id, task_num=target.task_num, at=now,
        )
    conn.commit()
    _emit_work_claimed(
        session_id, claim_id, target,
        linked_path_claim_ids=[], reason=reason,
    )
    row = _get_claim(conn, claim_id)
    # Acquisition registers no linked path claims (pure process lock).
    row["linked_path_claim_ids"] = []
    return row


# ---------------------------------------------------------------------------
# Claim release
# ---------------------------------------------------------------------------


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
