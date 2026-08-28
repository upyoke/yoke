"""Stop-hook reminder that a live work claim may still need a next step.

Eligible only for a live work claim on a non-terminal, non-wait item.
Consumes ``chain_pending_state()`` for audit context and does not recompute
chain budget. Reinjections are rate-limited and capped independently for
each claimed item.

Channel: keep that single soft hold. Claude Stop can deliver
``hookSpecificOutput.additionalContext`` as turn-continuing feedback, but
Codex Stop continuation is only ``decision/block`` (additionalContext is
not a Stop field / not model-visible) and Cursor Stop continuation is only
``followup_message`` (``additional_context`` is not a Stop output). A
passive additional-context envelope therefore cannot be the cross-harness
reminder, so the hold channel stays and the reminder lives in the message
plus the widened allow set.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from yoke_contracts.turn_end_evidence import (
    PAYLOAD_KEY,
    TurnEndEvidence,
    UNAVAILABLE,
    extract_turn_end_evidence,
    read_transcript_tail,
)
from yoke_core.domain.workflow_runtime import (
    ENGINE_TERMINAL_STAGE_IDS,
    ENGINE_WAIT_STAGE_IDS,
)
from yoke_core.domain.time_parse import parse_timestamp_utc
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


REINJECTION_COOLDOWN = timedelta(minutes=30)
REINJECTION_CEILING = 3
REASON_REINJECTED = "promised_work_reinjected"
REASON_CAP_REACHED = "reinjection_cap_reached"
UNFINISHED_CLOSE_OUT = "lifecycle_close_out"
UNFINISHED_CLAIMED_ITEM = "claimed_item_in_progress"
EVIDENCE_UNAVAILABLE_REASON = "turn-evidence-unavailable"
DIRECTIVE = (
    "This session still holds a live work claim. Finish the current step "
    "if work remains; or release the claim if the work is finished or "
    "handed off; or stop deliberately and say why (blocked, waiting on "
    "the operator, parked)."
)
_HOLD_EXEMPT_STATUSES = (
    ENGINE_TERMINAL_STAGE_IDS | ENGINE_WAIT_STAGE_IDS | frozenset({"done"})
)


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
    from yoke_core.domain.work_claim_targets import scope_int_sql

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    item_id_scope = scope_int_sql(conn, "wc.scope", "item_id")
    row = conn.execute(
        f"""SELECT i.id AS item_id, i.status,
                    i.merged_at, i.merge_queue_landed_at
              FROM work_claims wc
              JOIN items i ON i.id = {item_id_scope}
             WHERE wc.session_id = {placeholder}
               AND wc.target_kind = 'item'
               AND wc.released_at IS NULL
             ORDER BY wc.id DESC
             LIMIT 1""",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "item_id": row["item_id"],
        "status": row["status"],
        "merged_at": row["merged_at"],
        "merge_queue_landed_at": row["merge_queue_landed_at"],
    }


def _item_blocks_hold(status: Any) -> bool:
    value = str(status or "").strip()
    return value in _HOLD_EXEMPT_STATUSES


def _reinjection_history(
    conn: Any,
    session_id: str,
    item_id: Any,
) -> tuple[Optional[str], int]:
    from yoke_core.domain import db_backend

    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"""SELECT MAX(created_at) AS last_hold_at,
                    COUNT(*) AS hold_count
              FROM events
             WHERE session_id = {placeholder}
               AND event_name = 'ChainEndDeferred'
               AND (envelope)::jsonb #>> '{{context,reason}}' = {placeholder}
               AND (envelope)::jsonb #>> '{{context,item_id}}' = {placeholder}""",
        (session_id, REASON_REINJECTED, str(item_id)),
    ).fetchone()
    if row is None:
        return None, 0
    stamped = str(row["last_hold_at"]) if row["last_hold_at"] else None
    return stamped, int(row["hold_count"] or 0)


def _at_reinjection_cap(
    conn: Any,
    session_id: str,
    item_id: Any,
    *,
    now: Optional[datetime] = None,
) -> bool:
    if REINJECTION_CEILING < 1:
        return True
    stamped, hold_count = _reinjection_history(conn, session_id, item_id)
    if hold_count < 1:
        return False
    if hold_count >= REINJECTION_CEILING:
        return True
    last_hold_at = parse_timestamp_utc(stamped)
    if last_hold_at is None:
        return True
    anchor = now or datetime.now(timezone.utc)
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    return anchor.astimezone(timezone.utc) < last_hold_at + REINJECTION_COOLDOWN


def _landed_but_open(claim: dict[str, Any]) -> bool:
    return bool(claim.get("merged_at") or claim.get("merge_queue_landed_at"))


def unfinished_work_name(claim: dict[str, Any]) -> str:
    """Name the work the cap is about to abandon."""
    if _landed_but_open(claim):
        return UNFINISHED_CLOSE_OUT
    return UNFINISHED_CLAIMED_ITEM


def recovery_for(claim: dict[str, Any]) -> str:
    """Recovery the next agent can run; status is never the landing signal."""
    ref = str(claim.get("item_id") or "")
    status = str(claim.get("status") or "")
    if _landed_but_open(claim):
        return (
            f"item {ref} is still {status} after landing; status is not the "
            "landing signal. Finish close-out with "
            f"`yoke merge item {ref}` (Dash) or `/yoke usher {ref}` "
            "(delivery). Confirm merged_at, the merge receipt, or git "
            "ancestry of the merge sha."
        )
    return DIRECTIVE


def _emit_deferred(
    *,
    conn: Any,
    session_id: str,
    item_id: Any,
    reason: str,
    cap_reached: bool,
    claim: Optional[dict[str, Any]] = None,
) -> None:
    from yoke_core.domain.scheduler_events import emit_chain_end_deferred
    from yoke_core.domain.sessions_render_end_chain_pending import (
        chain_pending_state,
        last_released_at,
    )

    state = chain_pending_state(conn, session_id)
    extras: dict[str, Any] = {}
    if cap_reached:
        held = claim or {"item_id": item_id}
        extras = {
            "unfinished_work": unfinished_work_name(held),
            "item_status": str(held.get("status") or "") or None,
            "recovery": recovery_for(held),
            "severity": "WARN",
        }
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
        **extras,
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
        if _at_reinjection_cap(conn, session_id, claim["item_id"]):
            _emit_deferred(
                conn=conn,
                session_id=session_id,
                item_id=claim["item_id"],
                reason=REASON_CAP_REACHED,
                cap_reached=True,
                claim=claim,
            )
            return _allow()
        _emit_deferred(
            conn=conn,
            session_id=session_id,
            item_id=claim["item_id"],
            reason=REASON_REINJECTED,
            cap_reached=False,
            claim=claim,
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
    "REINJECTION_CEILING",
    "REINJECTION_COOLDOWN",
    "UNFINISHED_CLAIMED_ITEM",
    "UNFINISHED_CLOSE_OUT",
    "evaluate",
    "recovery_for",
    "unfinished_work_name",
]
