"""Envelopes the delivery plane owed an attempt and did not deliver.

A steering seat reads this section to find a worker still waiting on a
message. What it needs to separate is a delivery that has not finished yet
from one that is not coming, and only two facts do that: whether anything
was attempted, and how the last attempt ended.

Both were previously invisible. The section waited a flat ten minutes on the
envelope's age before saying anything at all, so a worker already silent for
seventeen minutes when the message arrived bought another ten of quiet — and
in one night four steering waits were abandoned by hand inside that window.
Meanwhile every wake behind them was failing for one nameable reason, and
because the section reported neither the attempt count nor the reason, the
seat's only visible signal was a holder that had gone quiet.

So the two shapes surface on their own clocks. A zero-attempt envelope
appears once the plane owed an attempt and did not make one. It owes one as
soon as the wake sweep would escalate — that is, once the recipient has been
silent for the acknowledgement grace window, counted on the recipient's own
clock rather than the envelope's, so silence that accrued before the message
counts. One relay poll after that moment the attempt should exist, and its
absence is the finding.

A failed attempt appears at once, whatever the age, and names its
diagnostic — an attempt that already ended badly has nothing left to wait
for.

One shape is neither: a recipient inside a tool call that has not returned
is silent because no hook runs until it does, not because its route
stopped. The delivery plane leaves such an envelope alone deliberately, so
the row says which — a seat reading "recipient turn in flight since
15:39Z" knows the wait is a long call finishing, not a worker to revive.
The row that hid this named only "last attempt failed", after a resume was
spawned against a worker twenty-one minutes into a merge wait.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping

from yoke_contracts.session_control.capabilities import native_wake_supported
from yoke_contracts.session_control.evidence import (
    valid_native_diagnostic_reference,
)
from yoke_contracts.session_control.wake_delivery import (
    delivery_attempt_diagnostic,
    delivery_attempt_failed,
)
from yoke_core.domain import json_helper
from yoke_core.domain.session_activity_state import (
    OPEN_TOOL_CALL_COLUMN,
    open_tool_call_select,
)
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_relay_policy import effective_relay_policy
from yoke_core.domain.session_message_starvation import hook_route_silent_since


@dataclass(frozen=True)
class StarvedDelivery:
    """One session with envelopes the delivery plane never injected."""

    session_id: str
    envelope_count: int
    oldest_seconds: int
    #: Why the wake sweep already escalated, when it has; empty otherwise.
    wake_escalation: str = ""
    #: True when the recipient's surface is woken only by its own operator,
    #: so the finding is an ask to that person rather than work for the seat.
    operator_wake: bool = False
    #: How many of these envelopes the plane attempted at all. Zero is the
    #: shape that says it never tried for any of them.
    attempt_count: int = 0
    #: How the last attempt failed, named. Empty when nothing was attempted.
    diagnostic: str = ""
    #: The diagnostic reference that attempt left on its own machine, so the
    #: row can name the exact capture rather than the session's newest file.
    evidence_id: str = ""
    #: When the recipient's still-running tool call started. Non-empty means
    #: the wait is a turn genuinely in flight, which the delivery plane is
    #: right not to resume — the envelope lands on that call's own hook.
    turn_in_flight_since: str = ""


def _last_attempts(
    conn: Any, *, project_id: int, marker: str
) -> dict[tuple[str, str], tuple[str, Mapping[str, Any]]]:
    """Return each pending receipt's most recent attempt, keyed by receipt."""
    rows = conn.execute(
        f"""SELECT a.message_id AS message_id,
                   a.target_session_id AS target_session_id,
                   a.result_code AS result_code,
                   a.evidence AS evidence
              FROM session_message_attempts a
              JOIN session_message_recipients r
                ON r.message_id = a.message_id
               AND r.session_id = a.target_session_id
             WHERE r.state = 'pending'
               AND COALESCE(r.injection_count, 0) = 0
               AND r.project_id = {marker}
             ORDER BY a.started_at, a.attempt_id""",
        (int(project_id),),
    ).fetchall()
    latest: dict[tuple[str, str], tuple[str, Mapping[str, Any]]] = {}
    for raw in rows:
        row = dict(raw)
        evidence = row.get("evidence")
        if isinstance(evidence, str):
            try:
                evidence = json_helper.loads_text(evidence)
            except (TypeError, ValueError):
                evidence = {}
        latest[(str(row["message_id"]), str(row["target_session_id"]))] = (
            str(row.get("result_code") or ""),
            evidence if isinstance(evidence, Mapping) else {},
        )
    return latest


def starved_deliveries(
    conn: Any,
    *,
    project_id: int,
    now: str,
) -> tuple[StarvedDelivery, ...]:
    """Envelopes still pending and never injected, whose recipient went quiet.

    Sender is deliberately not a filter: a worker-to-worker envelope starves
    exactly like a steerer-sent one. Ended and terminated recipients are
    excluded -- an envelope addressed to a session that is gone is not a
    worker waiting on a message, and there is nothing left to revive.

    Grouped by recipient because the action is per recipient: one session
    with four stuck envelopes is one worker to wake, not four findings.
    """
    from yoke_core.domain.steering_fleet_report_detectors import (
        age_seconds,
        marker,
        parse_stamp,
    )

    placeholder = marker(conn)
    # When the plane owes an attempt, and how long after that its absence is
    # the plane's failure rather than the next poll's ordinary work.
    grace = timedelta(
        seconds=int(project_policy(conn, int(project_id)).wake_ack_grace_seconds)
    )
    sla = timedelta(
        seconds=int(effective_relay_policy(conn, [int(project_id)]).poll_seconds)
    )
    attempts = _last_attempts(conn, project_id=project_id, marker=placeholder)
    open_call = open_tool_call_select(conn, session_alias="s")
    rows = conn.execute(
        f"""SELECT r.message_id AS message_id,
                   r.session_id AS session_id,
                   r.created_at AS created_at,
                   r.wake_escalation AS wake_escalation,
                   s.executor_surface AS executor_surface,
                   s.last_tool_call_at AS last_tool_call_at
                   {open_call}
              FROM session_message_recipients r
              JOIN harness_sessions s ON s.session_id = r.session_id
             WHERE r.state = 'pending'
               AND COALESCE(r.injection_count, 0) = 0
               AND r.project_id = {placeholder}
               AND s.ended_at IS NULL
               AND s.terminated_at IS NULL""",
        (int(project_id),),
    ).fetchall()
    oldest: dict[str, int] = {}
    counts: dict[str, int] = {}
    attempted: dict[str, int] = {}
    escalations: dict[str, str] = {}
    diagnostics: dict[str, str] = {}
    references: dict[str, str] = {}
    in_flight_since: dict[str, str] = {}
    operator_woken: set[str] = set()
    current = parse_stamp(now)
    for raw in rows:
        record = dict(raw)
        sent_at = str(record.get("created_at") or "")
        waited = age_seconds(sent_at, now)
        if waited is None:
            continue
        acted = str(record.get("last_tool_call_at") or "")
        if acted and parse_stamp(acted) >= parse_stamp(sent_at):
            # The recipient has run a tool since the send, so this envelope is
            # that session's ordinary backlog rather than a stuck delivery.
            continue
        session_id = str(record["session_id"])
        result_code, evidence = attempts.get(
            (str(record["message_id"]), session_id), ("", {})
        )
        diagnostic = delivery_attempt_diagnostic(result_code, evidence)
        if not result_code:
            # Nothing was attempted. The plane owes an attempt once the
            # recipient's silence has run past the wake SLA, and this row is
            # the evidence that it did not make one.
            silent_since = hook_route_silent_since(
                {
                    "last_tool_call_at": acted or None,
                    "message_created_at": sent_at,
                }
            )
            if silent_since is None:
                continue
            owed_at = max(silent_since + grace, parse_stamp(sent_at))
            if owed_at + sla > current:
                continue
        elif not delivery_attempt_failed(result_code):
            # An attempt is in flight or already delivered this receipt.
            continue
        counts[session_id] = counts.get(session_id, 0) + 1
        attempted[session_id] = attempted.get(session_id, 0) + bool(result_code)
        oldest[session_id] = max(oldest.get(session_id, 0), waited)
        if diagnostic:
            diagnostics[session_id] = diagnostic
        reference = valid_native_diagnostic_reference(
            evidence.get("native_diagnostic_ref")
        )
        if reference is not None:
            references[session_id] = reference
        # A recipient the sweep already escalated needs no hand resume, so
        # the finding says which absence authorized that wake rather than
        # reading like an envelope nothing has acted on.
        escalation = str(record.get("wake_escalation") or "")
        if escalation:
            escalations[session_id] = escalation
        # A recipient inside an unreturned tool call is working, not stuck.
        # Naming the call is what separates "nothing is coming" from "the
        # envelope lands when this finishes".
        open_since = str(record.get(OPEN_TOOL_CALL_COLUMN) or "")
        if open_since:
            in_flight_since[session_id] = open_since
        # A desktop recipient is never resumed by Yoke, so this row is not
        # a worker to revive; it names a chat only its operator can open.
        if not native_wake_supported(str(record.get("executor_surface") or "")):
            operator_woken.add(session_id)
    return tuple(
        StarvedDelivery(
            session_id=session_id,
            envelope_count=counts[session_id],
            oldest_seconds=oldest[session_id],
            wake_escalation=escalations.get(session_id, ""),
            operator_wake=session_id in operator_woken,
            attempt_count=attempted.get(session_id, 0),
            diagnostic=diagnostics.get(session_id, ""),
            evidence_id=references.get(session_id, ""),
            turn_in_flight_since=in_flight_since.get(session_id, ""),
        )
        for session_id in sorted(oldest, key=lambda key: (-oldest[key], key))
    )


__all__ = ["StarvedDelivery", "starved_deliveries"]
