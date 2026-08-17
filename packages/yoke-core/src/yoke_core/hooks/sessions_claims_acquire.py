"""Typed work-claim acquisition, conflict detection, and stale reclaim."""

from __future__ import annotations

import json

from yoke_core.domain import db_backend
from yoke_core.domain import workflow_item_binding_lock as binding_lock
from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.sessions_claim_lifecycle_lock import (
    lock_session_rows_for_claim_lifecycle,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
    validate_work_claim_target,
)
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    make_epic_task_target,
    make_item_target,
)

from yoke_core.hooks.sessions_event_emit import _emit_event
from yoke_core.hooks.sessions_claim_reclaim import (
    reclaim_stale_conflicts,
)
from yoke_core.hooks.sessions_focus import (
    _now_iso,
    _require_active_session,
    _set_current_item,
)


CLAIM_CONFLICT_NEXT_STEPS = (
    "Stop, coordinate with the holder, or wait for the holder to release."
)
CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING = (
    "Do NOT paste the holder session id into actor.session_id, "
    "--session-id, or any other function-call envelope — "
    "it is a coordination identifier, not an authority."
)


def _format_claim_conflict_message(target_label: str, holder_session_id: str) -> str:
    return (
        f"work target '{target_label}' already claimed by session "
        f"'{holder_session_id}'. {CLAIM_CONFLICT_NEXT_STEPS} "
        f"{CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING}"
    )


def _self_clause(target: WorkClaimTarget) -> tuple[str, list]:
    if target.kind == TARGET_KIND_ITEM:
        return ("target_kind='item' AND item_id=%s", [target.item_id])
    if target.kind == TARGET_KIND_EPIC_TASK:
        return (
            "target_kind='epic_task' AND epic_id=%s AND task_num=%s",
            [target.epic_id, target.task_num],
        )
    return (
        "target_kind='process' AND process_key=%s",
        [target.process_key],
    )


def _conflict_clause(target: WorkClaimTarget, alias: str = "") -> tuple[str, list]:
    p = f"{alias}" if alias else ""
    if target.kind == TARGET_KIND_PROCESS:
        return (
            f"{p}target_kind='process' AND {p}conflict_group=%s",
            [target.conflict_group],
        )
    if target.kind == TARGET_KIND_ITEM:
        return (
            f"{p}target_kind='item' AND {p}item_id=%s",
            [target.item_id],
        )
    return (
        f"{p}target_kind='epic_task' AND {p}epic_id=%s AND {p}task_num=%s",
        [target.epic_id, target.task_num],
    )


def cmd_claim(
    conn,
    session_id: str,
    target_kind: str,
    *,
    item_id: int | None = None,
    epic_id: int | None = None,
    task_num: int | None = None,
    process_key: str | None = None,
    conflict_group: str | None = None,
    reason: str | None = None,
) -> str:
    if target_kind == TARGET_KIND_ITEM:
        if item_id is None:
            raise ValueError("--item-id is required for target_kind=item")
        target: WorkClaimTarget = make_item_target(int(item_id))
    elif target_kind == TARGET_KIND_EPIC_TASK:
        if epic_id is None or task_num is None:
            raise ValueError(
                "--epic-id and --task-num are required for target_kind=epic_task"
            )
        target = make_epic_task_target(int(epic_id), int(task_num))
    elif target_kind == TARGET_KIND_PROCESS:
        if not process_key or not conflict_group:
            raise ValueError(
                "--process-key and --conflict-group are required for "
                "target_kind=process"
            )
        target = WorkClaimTarget(
            kind=TARGET_KIND_PROCESS,
            process_key=process_key,
            conflict_group=conflict_group,
        )
    else:
        raise ValueError(
            f"target_kind must be one of item/epic_task/process; got {target_kind!r}"
        )

    return _claim_typed(conn, session_id, target, reason=reason)


@binding_lock.rollback_workflow_binding_write_errors
def _claim_typed(
    conn,
    session_id: str,
    target: WorkClaimTarget,
    *,
    reason: str | None = None,
) -> str:
    now = _now_iso()
    _require_active_session(conn, session_id)
    target_label = target.render()

    self_where, self_params = _self_clause(target)
    conflict_where_unaliased, conflict_params = _conflict_clause(target)
    conflict_where_aliased, _ = _conflict_clause(target, alias="wc.")
    session_cols = set(_schema_get_columns(conn, "harness_sessions"))
    event_at_expr = (
        "ases.last_tool_call_at" if "last_tool_call_at" in session_cols else "NULL"
    )
    conflict_claims = query_rows(
        conn,
        f"SELECT wc.id, wc.session_id, ases.ended_at, ases.executor, "
        f"COALESCE(wc.last_heartbeat, ases.last_heartbeat, wc.claimed_at) AS activity_at, "
        f"{event_at_expr} AS event_at "
        f"FROM work_claims wc "
        f"LEFT JOIN harness_sessions ases ON ases.session_id = wc.session_id "
        f"WHERE {conflict_where_aliased} "
        f"AND wc.released_at IS NULL "
        f"AND wc.claim_type='exclusive' AND wc.session_id <> %s",
        (*conflict_params, session_id),
    )
    reclaim_stale_conflicts(
        conn,
        conflict_claims,
        target=target,
        target_label=target_label,
        attempting_session_id=session_id,
        now=now,
    )

    existing = query_scalar(
        conn,
        f"SELECT session_id FROM work_claims "
        f"WHERE {conflict_where_unaliased} AND released_at IS NULL "
        f"AND claim_type='exclusive' AND session_id <> %s",
        (*conflict_params, session_id),
    )
    if existing:
        from yoke_core.domain.sessions import clean_stale_harness_sessions

        try:
            clean_stale_harness_sessions(conn)
        except Exception:
            if db_backend.connection_is_postgres(conn):
                conn.rollback()
            pass
        existing = query_scalar(
            conn,
            f"SELECT session_id FROM work_claims "
            f"WHERE {conflict_where_unaliased} AND released_at IS NULL "
            f"AND claim_type='exclusive' AND session_id <> %s",
            (*conflict_params, session_id),
        )
    # End claim-row cleanup before taking the parent item lock.
    conn.commit()
    if existing:
        raise PermissionError(_format_claim_conflict_message(target_label, existing))
    lock_session_rows_for_claim_lifecycle(conn, (session_id,))
    _require_active_session(conn, session_id)
    binding_lock.lock_work_claim_target_workflow_binding(conn, target)
    try:
        validate_work_claim_target(conn, target)
    except WorkflowItemBindingError as exc:
        raise PermissionError(str(exc)) from exc

    dup = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM work_claims "
        f"WHERE session_id=%s AND {self_where} AND released_at IS NULL",
        (session_id, *self_params),
    )
    if dup:
        conn.commit()
        return f"Claimed: {target_label} by {session_id} (already owned)"
    existing = query_scalar(
        conn,
        f"SELECT session_id FROM work_claims "
        f"WHERE {conflict_where_unaliased} AND released_at IS NULL "
        f"AND claim_type='exclusive' AND session_id <> %s",
        (*conflict_params, session_id),
    )
    if existing:
        raise PermissionError(_format_claim_conflict_message(target_label, existing))

    cursor = conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, item_id, epic_id, task_num, "
        " process_key, conflict_group, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'exclusive', %s, %s) "
        "RETURNING id",
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
        ),
    )
    new_claim_id = int(cursor.fetchone()[0])
    if target.kind == TARGET_KIND_ITEM:
        _set_current_item(conn, session_id, str(target.item_id))
    from yoke_core.domain.claim_chain_state import (
        record_claim_reason,
        touch_epic_task_activity,
    )

    record_claim_reason(conn, claim_id=new_claim_id, reason=reason)
    _activity_target = (
        target.item_id if target.kind == TARGET_KIND_ITEM else target.epic_id
    )
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity

        touch_item_activity(conn, item_id=_activity_target)
    if target.kind == TARGET_KIND_EPIC_TASK:
        touch_epic_task_activity(
            conn,
            epic_id=target.epic_id,
            task_num=target.task_num,
            at=now,
        )
    conn.commit()
    event_ctx = {
        "target_kind": target.kind,
        "target_label": target_label,
        "claim_type": "exclusive",
        "claim_id": new_claim_id,
        "claimed_at": now,
    }
    if reason:
        event_ctx["claim_reason_intent"] = reason
    if target.kind == TARGET_KIND_ITEM:
        event_ctx["item_id"] = str(target.item_id)
    elif target.kind == TARGET_KIND_EPIC_TASK:
        event_ctx["epic_id"] = target.epic_id
        event_ctx["task_num"] = target.task_num
    else:
        event_ctx["process_key"] = target.process_key
        event_ctx["conflict_group"] = target.conflict_group
    _emit_event(
        conn,
        session_id,
        "WorkClaimed",
        json.dumps(event_ctx),
        item_id=str(target.item_id) if target.kind == TARGET_KIND_ITEM else None,
        task_num=target.task_num if target.kind == TARGET_KIND_EPIC_TASK else None,
    )
    return f"Claimed: {target_label} by {session_id}"


__all__ = [
    "CLAIM_CONFLICT_HOLDER_AUTHORITY_WARNING",
    "CLAIM_CONFLICT_NEXT_STEPS",
    "_claim_typed",
    "_conflict_clause",
    "_format_claim_conflict_message",
    "_self_clause",
    "cmd_claim",
]
