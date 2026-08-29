"""Work-claim release / inspection command handlers (typed targets).

Owns ``release`` of a single claim, ``release-all`` for a session,
``reclaim`` for stale-session recovery, and the read-only
``list-claims`` / ``who-claims`` introspection commands. The acquire
path (``claim``) lives in the
:mod:`yoke_core.hooks.sessions_claims_acquire` sibling and is
re-exported here so legacy import paths keep working.
"""

from __future__ import annotations

import json

from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.sessions_render_attribution import (
    release_current_item_focus,
    release_item_focus_if_current,
)
from yoke_core.domain.work_claim_targets import (
    WorkClaimTarget,
    from_row as target_from_row,
    scope_int_sql,
)
from yoke_core.api.service_client_shared_session_resolver import current_session_id

from yoke_core.hooks.sessions_claims_acquire import (  # noqa: F401
    _claim_typed,
    _conflict_clause,
    _self_clause,
    cmd_claim,
)
from yoke_core.hooks.sessions_event_emit import (
    _coerce_task_num,
    _emit_event,
)
from yoke_core.hooks.sessions_focus import (
    _clear_current_item,
    _format_row,
    _now_iso,
    _require_active_session,
)
from yoke_core.domain.work_claim_target_sql import LIVENESS_BOUND_SQL


def _target(kind: object, scope: object) -> WorkClaimTarget:
    return target_from_row({"target_kind": kind, "scope": scope})


def _target_context(target: WorkClaimTarget) -> dict[str, object]:
    context: dict[str, object] = {
        "target_kind": target.kind,
        "scope": dict(target.scope),
    }
    context.update(target.scope)
    return context


def _event_item(target: WorkClaimTarget) -> object:
    return (
        target.item_id
        or target.epic_id
        or (f"process:{target.process_key}" if target.process_key else None)
    )


def cmd_release(conn, claim_id: int, reason: str = "released") -> str:
    now = _now_iso()
    row = query_one(
        conn,
        "SELECT COALESCE(session_id, '') as sid, COALESCE(released_at, '') as rel, "
        "target_kind, scope "
        "FROM work_claims WHERE id=%s",
        (claim_id,),
    )
    if row is None:
        raise LookupError(f"claim '{claim_id}' not found")
    if row["rel"]:
        raise PermissionError(f"claim '{claim_id}' has already been released")
    target = _target(row["target_kind"], row["scope"])

    if target.item_id is not None and row["sid"]:
        release_item_focus_if_current(conn, row["sid"], target.item_id)
    conn.execute(
        "UPDATE work_claims SET released_at=%s, release_reason=%s "
        "WHERE id=%s AND released_at IS NULL",
        (now, reason, claim_id),
    )
    # The caller's release intent is first-class claim state.
    from yoke_core.domain.claim_chain_state import record_release_intent

    record_release_intent(conn, claim_id=claim_id, intent=reason)
    # Deliberate claim release is real item activity (R1 board-activity
    # semantics); process-target releases are not item-scoped.
    _activity_target = target.item_id or target.epic_id
    if _activity_target:
        from yoke_core.domain.item_activity import touch_item_activity

        touch_item_activity(conn, item_id=_activity_target)
    conn.commit()

    context = _target_context(target)
    context.update({"claim_id": claim_id, "release_reason": reason})
    _emit_event(
        conn,
        row["sid"] or "unknown",
        "WorkReleased",
        json.dumps(context),
        item_id=_event_item(target),
        task_num=_coerce_task_num(target.task_num),
    )
    return f"Released claim: {claim_id} (reason: {reason})"


def cmd_release_all(conn, session_id: str, reason: str = "released") -> str:
    now = _now_iso()
    active_claims = query_rows(
        conn,
        "SELECT id, target_kind, scope "
        "FROM work_claims WHERE session_id=%s AND released_at IS NULL "
        f"AND {LIVENESS_BOUND_SQL} ORDER BY claimed_at ASC, id ASC",
        (session_id,),
    )
    conn.execute(
        "UPDATE work_claims SET released_at=%s, release_reason=%s "
        "WHERE session_id=%s AND released_at IS NULL "
        f"AND {LIVENESS_BOUND_SQL}",
        (now, reason, session_id),
    )
    # The caller's release intent is first-class claim state.
    from yoke_core.domain.claim_chain_state import (
        record_release_intent_for_session,
    )

    record_release_intent_for_session(
        conn,
        session_id=session_id,
        released_at=now,
        intent=reason,
    )
    # Match the canonical per-claim release path: focus the session kept
    # on a just-released claim is structurally stale, so it archives here
    # and falls back to whatever claim the liveness bound left active.
    # This keeps the legacy `release-all-claims` CLI in parity with the
    # typed release siblings so the path-claim pre-edit guard does not
    # read a dangling focus link after a release.
    release_current_item_focus(conn, session_id, commit=False)
    # Deliberate claim release is real item activity (R1 board-activity
    # semantics); process-target releases are not item-scoped.
    from yoke_core.domain.item_activity import touch_item_activity

    for claim in active_claims:
        target = _target(claim[1], claim[2])
        _activity_target = target.item_id or target.epic_id
        if _activity_target:
            touch_item_activity(conn, item_id=_activity_target)
    conn.commit()

    for claim in active_claims:
        cid = claim[0]
        target = _target(claim[1], claim[2])
        ctx = _target_context(target)
        ctx.update(
            {
                "claim_id": cid,
                "release_reason": reason,
            }
        )
        _emit_event(
            conn,
            session_id,
            "WorkReleased",
            json.dumps(ctx),
            item_id=_event_item(target),
            task_num=_coerce_task_num(target.task_num),
        )

    return f"Released all claims for session: {session_id}"


def cmd_reclaim(conn, session_id: str) -> str:
    now = _now_iso()
    _require_active_session(conn, session_id)

    active_claims = query_rows(
        conn,
        "SELECT id, target_kind, scope "
        "FROM work_claims WHERE session_id=%s AND released_at IS NULL "
        f"AND {LIVENESS_BOUND_SQL} ORDER BY claimed_at ASC, id ASC",
        (session_id,),
    )
    _clear_current_item(conn, session_id)
    conn.execute(
        "UPDATE work_claims SET released_at=%s, release_reason='reclaimed' "
        "WHERE session_id=%s AND released_at IS NULL "
        f"AND {LIVENESS_BOUND_SQL}",
        (now, session_id),
    )
    conn.execute(
        "UPDATE harness_sessions SET ended_at=%s WHERE session_id=%s",
        (now, session_id),
    )
    conn.commit()

    for claim in active_claims:
        cid = claim[0]
        target = _target(claim[1], claim[2])
        ctx = _target_context(target)
        ctx.update(
            {
                "claim_id": cid,
                "reason": "stale_session_reclaimed",
            }
        )
        _emit_event(
            conn,
            session_id,
            "WorkReclaimed",
            json.dumps(ctx),
            item_id=_event_item(target),
            task_num=_coerce_task_num(target.task_num),
        )

    return f"Reclaimed session: {session_id}"


def cmd_list_claims(conn, session_id: str) -> str:
    rows = query_rows(
        conn,
        "SELECT id, session_id, target_kind, "
        "scope, "
        "claim_type, claimed_at, last_heartbeat "
        "FROM work_claims WHERE session_id=%s AND released_at IS NULL "
        "ORDER BY claimed_at DESC",
        (session_id,),
    )
    return "\n".join(_format_row(row) for row in rows)


WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE = (
    "WARNING: this item is actively claimed by another session "
    "('{holder}'). The holder session id is a coordination identifier, "
    "not an authority. Do NOT paste it into actor.session_id, "
    "--session-id, or any other function-call envelope. "
    "Stop, coordinate with the holder, or wait for the holder to release."
)


def cmd_who_claims(
    conn,
    item_id: str,
    *,
    caller_session_id: str | None = None,
    current_episode: bool = False,
) -> str:
    """Look up active claim for an item-target.

    Appends a warning line when the resolved caller session is not the
    active holder (or no caller session is set). The first line is always
    the canonical ``_format_row`` claim row so operator/debug parsing is
    preserved.

    When ``current_episode=True``, the row's episode scope is appended
    inline as ``episode_scope=<scope>``. Inherited claims (acquired in
    a prior episode) are visible — they are intentionally inherited
    across episodes and audit must show that inheritance fact. The
    classification uses the boundary helper in
    :mod:`yoke_core.domain.events_current_episode`.
    """
    from yoke_core.domain.yok_n_parser import parse_item_argument

    normalized = str(parse_item_argument(item_id, conn=conn))
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    rows = query_rows(
        conn,
        f"SELECT wc.id, wc.session_id, {item_scope} AS item_id, "
        "wc.claim_type, wc.claimed_at "
        "FROM work_claims wc "
        f"WHERE wc.target_kind='item' AND {item_scope}=%s "
        "AND wc.released_at IS NULL LIMIT 1",
        (int(normalized),),
    )
    if not rows:
        return ""
    lines = [_format_row(row) for row in rows]
    holder = rows[0][1]
    if current_episode and holder:
        from yoke_core.domain.events_current_episode import (
            claim_episode_scope,
            resolve_current_episode_boundary,
        )

        boundary = resolve_current_episode_boundary(conn, holder)
        scope = claim_episode_scope(
            claim_claimed_at=rows[0][4],
            boundary_created_at=boundary,
        )
        lines.append(f"episode_scope={scope}")
        if boundary is None:
            lines.append(
                f"episode_boundary=none (no episode_started_at recorded "
                f"for session '{holder}')"
            )
        else:
            lines.append(f"episode_boundary={boundary}")
    if caller_session_id is None:
        caller_session_id = current_session_id()
    if holder and caller_session_id != holder:
        lines.append(WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE.format(holder=holder))
    return "\n".join(lines)


__all__ = [
    "WHO_CLAIMS_NON_HOLDER_WARNING_TEMPLATE",
    "cmd_claim",
    "cmd_list_claims",
    "cmd_reclaim",
    "cmd_release",
    "cmd_release_all",
    "cmd_who_claims",
]
