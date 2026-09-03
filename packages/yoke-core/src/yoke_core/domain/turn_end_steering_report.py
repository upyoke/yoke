"""Route a steering-launched session's Stop reports to the steering holder.

The relay saves a worker the step of re-sending what it just said, so it
belongs to the sessions a steering seat launched and to nothing else. The
covering route once selected the inverse — any claim-holding session with no
launch row — which made an operator's own conversation a worker the moment
it claimed an item in a steered project: one desktop session mailed 23 whole
design-discussion replies to the seat, none of them a report. Provenance is
the launch row (``session_launches.registered_session_id`` naming the origin
session, with ``origin = 'steering'``), because no ``harness_sessions`` column
records who launched a session — ``entrypoint`` and ``executor_surface`` say
what it is, not who asked for it. An operator-launched session and an
operator-opened one both reach the seat deliberately with
``yoke say --steering``.

The item a report is addressed within comes from
:mod:`yoke_core.domain.session_item_scope`, so the last turn a worker stops
on -- the one after close-out released its item claim, carrying the DONE
report -- still routes. Requiring a LIVE claim dropped exactly that turn.

A relayed worker stops every few minutes while a gate runs, and the machinery
mails whatever it said. Bodies that were pure wait -- "Waiting for the run.",
"I will report when it lands.", "Holding." -- cost one seat a dozen hand
acknowledgements in an evening and changed nothing it would do. So the body
must clear
:func:`yoke_core.domain.session_message_substance.carries_actionable_signal`
before it is sent; a body that clears nothing is recorded as
``SteeringReportSkipped`` instead, which still shows the seat the worker
stopped without costing it an inbox row. The send path's own refusal is
unchanged: a sender who chose the words is still refused only for an
unambiguous progress tick.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGIN_STEERING
from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.turn_end_evidence import (
    REPORT_PAYLOAD_KEY,
    TurnEndReport,
    extract_turn_end_report,
    read_transcript_tail,
    steering_report_idempotency_key,
)
from yoke_core.domain import db_backend
from yoke_core.domain.events import emit_event
from yoke_core.domain.session_item_scope import session_item_scope
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_substance import carries_actionable_signal
from yoke_core.domain.steering_scope_coverage import covering_seat
from yoke_core.domain.steering_scope_membership import item_coverage_target
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


ROUTED_REASON = "steering_report_routed"
SKIPPED_REASON = "steering_report_skipped_non_substantive"
EVENT_STEERING_REPORT_SKIPPED = "SteeringReportSkipped"
# Enough of the body to recognize the turn on the ledger, not a transcript.
SKIPPED_BODY_EXCERPT_CHARS = 500


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _covering_route(conn: Any, session_id: str) -> dict[str, Any] | None:
    """Steering-launch provenance plus the seat covering this session's item."""
    scope = session_item_scope(conn, session_id)
    if scope is None:
        return None
    marker = _p(conn)
    row = conn.execute(
        f"""SELECT origin.actor_id AS sender_actor_id
              FROM harness_sessions origin
             WHERE origin.session_id = {marker}
               AND origin.actor_id IS NOT NULL
               AND EXISTS (
                   SELECT 1 FROM session_launches launch
                    WHERE launch.registered_session_id = origin.session_id
                      AND launch.origin = {marker}
               )""",
        (session_id, LAUNCH_ORIGIN_STEERING),
    ).fetchone()
    if row is None:
        return None
    seat = covering_seat(
        conn,
        item_coverage_target(
            conn,
            project_id=scope.project_id,
            item_id=scope.item_id,
        ),
    )
    if seat is None or str(seat["session_id"]) == str(session_id):
        return None
    return {
        "sender_actor_id": int(dict(row)["sender_actor_id"]),
        "recipient_session_id": str(seat["session_id"]),
    }


def route_turn_end_report(
    conn: Any,
    *,
    session_id: str,
    report: TurnEndReport,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Send one covered report, or record the skip when it clears no floor.

    Returns ``None`` when this session is not relayed at all, the send
    result when the report was mailed, and a ``skipped`` record when the
    body carried nothing for the seat to act on.
    """
    route = _covering_route(conn, session_id)
    if route is None:
        return None
    recipient_session_id = str(route["recipient_session_id"])
    if not carries_actionable_signal(report.body):
        return _record_skipped_report(
            conn,
            session_id=session_id,
            report=report,
            recipient_session_id=recipient_session_id,
        )
    result = send_message(
        conn,
        actor_id=int(route["sender_actor_id"]),
        sender_session_id=session_id,
        selector=RecipientSelector(session_ids=[recipient_session_id]),
        body=report.body,
        idempotency_key=steering_report_idempotency_key(session_id, report.fingerprint),
        now=now,
    )
    return {**result, "recipient_session_id": recipient_session_id}


def _record_skipped_report(
    conn: Any,
    *,
    session_id: str,
    report: TurnEndReport,
    recipient_session_id: str,
) -> dict[str, Any]:
    """Record the stop the seat is not being mailed, and report the skip."""
    body = report.body.strip()
    emit_event(
        EVENT_STEERING_REPORT_SKIPPED,
        event_kind="system",
        event_type="session_lifecycle",
        session_id=session_id,
        context={
            "recipient_session_id": recipient_session_id,
            "fingerprint": report.fingerprint,
            "reason": SKIPPED_REASON,
            "body_chars": len(body),
            "body_excerpt": body[:SKIPPED_BODY_EXCERPT_CHARS],
        },
        conn=conn,
    )
    return {
        "skipped": True,
        "reason": SKIPPED_REASON,
        "recipient_session_id": recipient_session_id,
    }


def _report_for(context: HookContext) -> TurnEndReport | None:
    payload = context.payload if isinstance(context.payload, dict) else {}
    if context.remote or REPORT_PAYLOAD_KEY in payload:
        return extract_turn_end_report(payload=payload)
    path = payload.get("transcript_path")
    transcript = read_transcript_tail(path) if isinstance(path, str) and path else None
    return extract_turn_end_report(payload=payload, transcript_text=transcript)


def _continue() -> HookDecision:
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def evaluate(context: HookContext) -> HookDecision:
    """Route a covered Stop report, then allow the harness turn to end."""
    if context.event_name != "Stop" or not context.session_id:
        return _continue()
    report = _report_for(context)
    if report is None:
        return _continue()
    try:
        from yoke_core.domain.db_helpers import connect

        conn = connect()
    except Exception:
        return _continue()
    try:
        routed = route_turn_end_report(
            conn,
            session_id=context.session_id,
            report=report,
            now=context.now,
        )
    except Exception:
        return _continue()
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if routed is None:
        return _continue()
    if routed.get("skipped"):
        # Nothing was mailed, so the rest of the Stop chain still owns this
        # turn exactly as it does for a session outside the relay.
        return HookDecision(
            outcome=Outcome.AUDIT_ONLY,
            next=Next.CONTINUE,
            audit_fields={
                "reason": SKIPPED_REASON,
                "recipient_session_id": routed["recipient_session_id"],
            },
        )
    return HookDecision(
        outcome=Outcome.ALLOW,
        next=Next.STOP,
        audit_fields={
            "reason": ROUTED_REASON,
            "message_id": routed["message_id"],
            "recipient_session_id": routed["recipient_session_id"],
        },
    )


__all__ = [
    "EVENT_STEERING_REPORT_SKIPPED",
    "ROUTED_REASON",
    "SKIPPED_BODY_EXCERPT_CHARS",
    "SKIPPED_REASON",
    "evaluate",
    "route_turn_end_report",
]
