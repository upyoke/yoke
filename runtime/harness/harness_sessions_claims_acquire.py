"""Work-claim acquisition (typed) — split out of harness_sessions_claims.py.

Owns the ``cmd_claim`` dispatch, the typed acquire path
(``_claim_typed``), and the per-kind WHERE-clause helpers used by both
acquisition and conflict detection. Stale-claim auto-reclaim and live-
session conflict checking live here too — the release/reclaim/list/who
commands stay in the parent module.
"""

from __future__ import annotations

import json

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.domain.session_reclaim_activity import (
    SCOPE_ITEM_CLAIM,
    classify_reclaimable,
)
from yoke_core.domain.session_staleness import activity_is_stale
from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    WorkClaimTarget,
    make_epic_task_target,
    make_item_target,
)

from runtime.harness.harness_sessions_event_emit import _emit_event
from runtime.harness.harness_sessions_focus import (
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
    """Conflict-detection WHERE fragment for ``target``.

    ``alias`` prefixes column names (e.g. ``alias='wc.'``) for joined queries.
    """
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
            f"target_kind must be one of item/epic_task/process; "
            f"got {target_kind!r}"
        )

    return _claim_typed(conn, session_id, target, reason=reason)


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
    dup = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM work_claims "
        f"WHERE session_id=%s AND {self_where} AND released_at IS NULL",
        (session_id, *self_params),
    )
    if dup:
        return f"Claimed: {target_label} by {session_id} (already owned)"

    conflict_where_unaliased, conflict_params = _conflict_clause(target)
    conflict_where_aliased, _ = _conflict_clause(target, alias="wc.")
    # Holder tool-activity freshness reads harness_sessions.last_tool_call_at
    # (stamped by the observe pipeline). Introspection keeps minimal
    # work-claim fixtures without the column working — absent reads NULL.
    session_cols = set(_schema_get_columns(conn, "harness_sessions"))
    event_at_expr = (
        "ases.last_tool_call_at"
        if "last_tool_call_at" in session_cols
        else "NULL"
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
    snapshot_stale_claims = [
        row for row in conflict_claims
        if row[2] is not None or (
            activity_is_stale(row[4], executor=row[3])
            and activity_is_stale(row[5], executor=row[3])
        )
    ]
    item_id_for_event = (
        str(target.item_id) if target.kind == TARGET_KIND_ITEM else None
    )
    for sc in snapshot_stale_claims:
        original_session_id = sc[1]
        # TOCTOU recheck inside the same transaction. Re-read
        # the holder's heartbeat plus latest tool-call event timestamp
        # using the shared reclaim activity classifier; if either signal
        # has moved into the freshness window since the snapshot, abort
        # the reclaim and emit ReclaimAborted instead of mutating the row.
        recheck = classify_reclaimable(
            conn, original_session_id, claim_id=sc[0],
        )
        if not recheck.is_reclaimable:
            evidence_payload = recheck.evidence.as_payload()
            _emit_event(
                conn,
                original_session_id,
                "ReclaimAborted",
                json.dumps({
                    "claim_id": sc[0],
                    "scope": SCOPE_ITEM_CLAIM,
                    "original_session_id": original_session_id,
                    "attempting_session_id": session_id,
                    "abort_reason": recheck.reason,
                    "executor": evidence_payload["executor"],
                    "effective_ttl_minutes": evidence_payload[
                        "effective_ttl_minutes"
                    ],
                    "original_session_last_heartbeat": evidence_payload[
                        "last_heartbeat"
                    ],
                    "original_session_last_event_at": evidence_payload[
                        "last_event_at"
                    ],
                    "target_kind": target.kind,
                    "target_label": target_label,
                }),
                item_id=item_id_for_event,
            )
            continue
        conn.execute(
            "UPDATE work_claims SET released_at=%s, release_reason='reclaimed' "
            "WHERE id=%s AND released_at IS NULL",
            (now, sc[0]),
        )
        _emit_event(
            conn,
            original_session_id,
            "WorkReclaimed",
            json.dumps({
                "claim_id": sc[0],
                "reason": "stale_item_claim_reclaimed",
                "target_kind": target.kind,
                "target_label": target_label,
            }),
            item_id=item_id_for_event,
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
            pass
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
    # Acquire reason is first-class claim state: verbatim reason +
    # canonical intent classification land on the row itself.
    from yoke_core.domain.claim_chain_state import (
        record_claim_reason,
        touch_epic_task_activity,
    )
    record_claim_reason(conn, claim_id=new_claim_id, reason=reason)
    # Claim acquire is real item activity (R1 board-activity semantics).
    _activity_target = target.item_id if target.kind == TARGET_KIND_ITEM else target.epic_id
    if _activity_target is not None:
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=_activity_target)
    if target.kind == TARGET_KIND_EPIC_TASK:
        # An epic-task acquire is task activity for chain-head freshness.
        touch_epic_task_activity(
            conn, epic_id=target.epic_id, task_num=target.task_num, at=now,
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
