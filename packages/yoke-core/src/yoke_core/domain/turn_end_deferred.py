"""Record why a promised-work turn ends or is held."""

from typing import Any, Optional

from yoke_core.domain.session_message_types import utc_now
from yoke_core.domain.session_recovery_facts import record_promised_work_hold
from yoke_core.domain.turn_end_relay_continuation import REASON_RELAY_WAKE_REFUSED
from yoke_core.domain.turn_end_unfinished_work import recovery_for, unfinished_work_name

REASON_REINJECTED = "promised_work_reinjected"
REASON_CONTINUATION_UNSUPPORTED = "stop_denial_continuation_unsupported"


def emit_deferred(
    *,
    conn: Any,
    session_id: str,
    item_id: Any,
    reason: str,
    cap_reached: bool,
    claim: Optional[dict[str, Any]] = None,
    blocking_item: str | None = None,
    gate_point: str | None = None,
) -> None:
    from yoke_core.domain.scheduler_events import emit_chain_end_deferred
    from yoke_core.domain.sessions_render_end_chain_pending import (
        chain_pending_state,
        last_released_at,
    )

    state = chain_pending_state(conn, session_id)
    extras: dict[str, Any] = {}
    if cap_reached or reason in (
        REASON_CONTINUATION_UNSUPPORTED,
        REASON_RELAY_WAKE_REFUSED,
    ):
        held = claim or {"item_id": item_id}
        extras = {
            "unfinished_work": unfinished_work_name(held),
            "item_status": str(held.get("status") or "") or None,
            "recovery": recovery_for(held),
            "severity": "WARN",
        }
    if reason == REASON_REINJECTED:
        # Recorded with the decision, not derived from its telemetry: the
        # hold is what the ceiling counts, and it must survive whatever
        # the events ledger retains.
        record_promised_work_hold(
            conn,
            session_id=session_id,
            item_id=item_id,
            at=utc_now(),
        )
        conn.commit()
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
        blocking_item=blocking_item,
        gate_point=gate_point,
        **extras,
    )


