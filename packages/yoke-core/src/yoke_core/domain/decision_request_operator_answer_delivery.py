"""Deliver an operator answer after its durable decision has committed."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.db_savepoint import SavepointLostError, savepoint

UNDELIVERED = "operator_question_undelivered"


def answer_text(request):
    action = request.get("resolution_action")
    if action == "freeform":
        return request.get("resolution_note") or ""
    return next(
        (
            option["label"]
            for option in request["subject_context"].get("options", [])
            if option["id"] == action
        ),
        action or "",
    )


def _recipient(conn, request):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.schema_work_claim_sql import scope_int_sql

    p = _p(conn)
    row = conn.execute(
        f"SELECT session_id FROM harness_sessions WHERE session_id={p} "
        "AND terminated_at IS NULL",
        (request["requesting_session_id"],),
    ).fetchone()
    if row is not None:
        return str(row[0])
    item_id = request["subject_context"].get("item_id")
    if item_id is None:
        return None
    item_scope = scope_int_sql(conn, "wc.scope", "item_id")
    row = conn.execute(
        "SELECT wc.session_id FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id=wc.session_id "
        "WHERE wc.target_kind='item' AND wc.released_at IS NULL "
        "AND hs.ended_at IS NULL AND hs.terminated_at IS NULL "
        f"AND {item_scope}={p} ORDER BY wc.id DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    return str(row[0]) if row else None


def deliver_answer(conn: Any, request: dict[str, Any]) -> None:
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.session_message_service import send_message
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake

    context = dict(request["subject_context"])
    if context.get("answer_delivery", {}).get("message_id"):
        return
    delivery = {
        "reason": UNDELIVERED,
        "recovery": "Read the answer with decision-requests list --mine and relay it to the item holder.",
    }
    try:
        recipient = _recipient(conn, request)
        if recipient:
            decider = request["decisions"][-1]
            body = (
                f"Operator answer to request {request['id']}: {context['question']}\n"
                f"Answer: {answer_text(request)}\nNote: {request.get('resolution_note') or ''}\n"
                f"Answered by {decider.get('actor_label') or decider['actor_id']}."
            )
            with savepoint(conn, "operator_answer_delivery", owns=False):
                sent = send_message(
                    conn,
                    actor_id=int(request["resolution_actor_id"]),
                    engine_sender=True,
                    sender_session_id=None,
                    selector=RecipientSelector(session_ids=[recipient]),
                    body=body,
                    idempotency_key=f"operator-question-answer:{request['id']}",
                    idempotency_intent_only=True,
                    commit=False,
                )
                mark_explicit_stopped_wake(
                    conn, message_id=sent["message_id"], session_id=recipient
                )
            delivery = {"message_id": sent["message_id"], "session_id": recipient}
    except SavepointLostError:
        raise
    except Exception as exc:
        delivery["detail"] = str(exc)
    context["answer_delivery"] = delivery
    conn.execute(
        f"UPDATE decision_requests SET subject_context={_p(conn)} WHERE id={_p(conn)}",
        (json.dumps(context, separators=(",", ":")), request["id"]),
    )
    conn.commit()
