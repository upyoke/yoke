"""Stop-hook gate that holds a turn open when promised work is still uncalled.

Eligible only for a live work claim on a non-terminal, unblocked item.
Consumes ``chain_pending_state()`` for audit context and does not recompute
chain budget. One reinjection without intervening tool-use is the cap.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_contracts.turn_end_evidence import (
    PAYLOAD_KEY,
    TurnEndEvidence,
    UNAVAILABLE,
    extract_turn_end_evidence,
    read_transcript_tail,
)
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


REINJECTION_LIMIT = 1
REASON_REINJECTED = "promised_work_reinjected"
REASON_CAP_REACHED = "reinjection_cap_reached"
EVIDENCE_UNAVAILABLE_REASON = "turn-evidence-unavailable"
DIRECTIVE = (
    "This session still holds a live work claim on a mid-lifecycle item. "
    "Perform the promised work now; do not end the turn."
)
_TERMINAL_STATUSES = frozenset({"done"})
_BLOCKED_STATUSES = frozenset({"blocked"})


def _allow() -> HookDecision:
    return HookDecision(outcome=Outcome.ALLOW, next=Next.CONTINUE)


def _hold() -> HookDecision:
    return HookDecision(
        outcome=Outcome.DENY,
        message=DIRECTIVE,
        block=True,
        next=Next.STOP,
        audit_fields={"reason": REASON_REINJECTED},
    )


def _evidence_for(context: HookContext) -> TurnEndEvidence:
    payload = context.payload if isinstance(context.payload, dict) else {}
    if context.remote:
        return extract_turn_end_evidence(payload=payload)
    if PAYLOAD_KEY in payload:
        return extract_turn_end_evidence(payload=payload)
    path = payload.get("transcript_path")
    text = read_transcript_tail(path) if isinstance(path, str) and path else None
    return extract_turn_end_evidence(payload=payload, transcript_text=text)


def _emit_unavailable(context: HookContext) -> None:
    from yoke_core.hooks.stdin import emit_session_hook_failed

    emit_session_hook_failed(
        hook_event=context.event_name or "Stop",
        executor=context.executor_family or "",
        reason=EVIDENCE_UNAVAILABLE_REASON,
        latency_ms=0,
        stdin_state="turn-evidence-unavailable",
        session_id_source="hook-payload",
        session_id=context.session_id or "",
    )


def _live_claim(conn: Any, session_id: str) -> Optional[dict[str, Any]]:
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"""SELECT i.id AS item_id, i.status
              FROM work_claims wc
              JOIN items i ON i.id = wc.item_id
             WHERE wc.session_id = {placeholder}
               AND wc.released_at IS NULL
             ORDER BY wc.id DESC
             LIMIT 1""",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {"item_id": row["item_id"], "status": row["status"]}


def _item_blocks_hold(status: Any) -> bool:
    value = str(status or "").strip()
    return value in _TERMINAL_STATUSES or value in _BLOCKED_STATUSES


def _envelope_reason(conn: Any, session_id: str, reason: str) -> Optional[str]:
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"""SELECT created_at
              FROM events
             WHERE session_id = {placeholder}
               AND event_name = 'ChainEndDeferred'
               AND (envelope)::jsonb #>> '{{context,reason}}' = {placeholder}
             ORDER BY created_at DESC
             LIMIT 1""",
        (session_id, reason),
    ).fetchone()
    if row is None or not row["created_at"]:
        return None
    return str(row["created_at"])


def _completed_tool_use_since(conn: Any, session_id: str, since: str) -> bool:
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"""SELECT 1 AS ok
              FROM events
             WHERE session_id = {placeholder}
               AND created_at > {placeholder}
               AND hook_event_name IN ('PreToolUse', 'PostToolUse')
             LIMIT 1""",
        (session_id, since),
    ).fetchone()
    return row is not None


def _at_reinjection_cap(conn: Any, session_id: str) -> bool:
    if REINJECTION_LIMIT < 1:
        return True
    stamped = _envelope_reason(conn, session_id, REASON_REINJECTED)
    if stamped is None:
        return False
    return not _completed_tool_use_since(conn, session_id, stamped)


def _emit_deferred(
    *,
    conn: Any,
    session_id: str,
    item_id: Any,
    reason: str,
    cap_reached: bool,
) -> None:
    from yoke_core.domain.scheduler_events import emit_chain_end_deferred
    from yoke_core.domain.sessions_render_end_chain_pending import (
        chain_pending_state,
        last_released_at,
    )

    state = chain_pending_state(conn, session_id)
    emit_chain_end_deferred(
        session_id=session_id,
        triggered_by="turn-end-promised-work-gate",
        checkpoint_step=state.step,
        max_chain_steps=state.max_chain_steps,
        handler_outcome=state.handler_outcome,
        chainable=state.chainable,
        action=state.action,
        item_id=str(item_id) if item_id is not None else state.item_id,
        last_release_at=last_released_at(conn, session_id),
        reason=reason,
        cap_reached=cap_reached,
    )


def evaluate(record: HookContext) -> HookDecision:
    """Hold an eligible Stop; allow every documented escape hatch."""
    if record.event_name != "Stop":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    evidence = _evidence_for(record)
    if evidence is UNAVAILABLE or not evidence.available:
        _emit_unavailable(record)
        return _allow()
    if evidence.question:
        return _allow()
    session_id = record.session_id
    if not session_id:
        return _allow()
    try:
        from yoke_core.domain.db_helpers import connect

        conn = connect()
    except Exception:
        return _allow()
    try:
        claim = _live_claim(conn, session_id)
        if claim is None:
            return _allow()
        if _item_blocks_hold(claim["status"]):
            return _allow()
        # Snapshot is consumed for the deferred event, never recomputed here.
        if _at_reinjection_cap(conn, session_id):
            _emit_deferred(
                conn=conn,
                session_id=session_id,
                item_id=claim["item_id"],
                reason=REASON_CAP_REACHED,
                cap_reached=True,
            )
            return _allow()
        _emit_deferred(
            conn=conn,
            session_id=session_id,
            item_id=claim["item_id"],
            reason=REASON_REINJECTED,
            cap_reached=False,
        )
        return _hold()
    except Exception:
        return _allow()
    finally:
        try:
            conn.close()
        except Exception:
            pass


__all__ = [
    "DIRECTIVE",
    "EVIDENCE_UNAVAILABLE_REASON",
    "REASON_CAP_REACHED",
    "REASON_REINJECTED",
    "REINJECTION_LIMIT",
    "evaluate",
]
