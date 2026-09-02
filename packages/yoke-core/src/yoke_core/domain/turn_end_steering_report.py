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
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.work_claim_targets import scope_int_sql
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome


ROUTED_REASON = "steering_report_routed"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _covering_route(conn: Any, session_id: str) -> dict[str, Any] | None:
    """Resolve steering-launch provenance, item scope, and the holder once."""
    item_id = scope_int_sql(conn, "current_claim.scope", "item_id")
    steering_project = scope_int_sql(conn, "steering.scope", "project_id")
    marker = _p(conn)
    row = conn.execute(
        f"""SELECT origin.actor_id AS sender_actor_id,
                   steering.session_id AS recipient_session_id,
                   item.project_id AS project_id
              FROM harness_sessions origin
              JOIN work_claims current_claim
                ON current_claim.session_id = origin.session_id
               AND current_claim.target_kind = 'item'
               AND current_claim.released_at IS NULL
              JOIN items item ON item.id = {item_id}
              JOIN work_claims steering
                ON steering.target_kind = 'steering'
               AND steering.released_at IS NULL
               AND {steering_project} = item.project_id
              JOIN harness_sessions holder
                ON holder.session_id = steering.session_id
               AND holder.ended_at IS NULL
             WHERE origin.session_id = {marker}
               AND origin.actor_id IS NOT NULL
               AND steering.session_id <> origin.session_id
               AND EXISTS (
                   SELECT 1 FROM session_launches launch
                    WHERE launch.registered_session_id = origin.session_id
                      AND launch.origin = {marker}
               )
             ORDER BY current_claim.id DESC, steering.id ASC
             LIMIT 1""",
        (session_id, LAUNCH_ORIGIN_STEERING),
    ).fetchone()
    return dict(row) if row is not None else None


def route_turn_end_report(
    conn: Any,
    *,
    session_id: str,
    report: TurnEndReport,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Persist one covered report through the existing message plane."""
    route = _covering_route(conn, session_id)
    if route is None:
        return None
    recipient_session_id = str(route["recipient_session_id"])
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
    return HookDecision(
        outcome=Outcome.ALLOW,
        next=Next.STOP,
        audit_fields={
            "reason": ROUTED_REASON,
            "message_id": routed["message_id"],
            "recipient_session_id": routed["recipient_session_id"],
        },
    )


__all__ = ["ROUTED_REASON", "evaluate", "route_turn_end_report"]
