"""Flip a launch whose worker ended without ever entering its mandate.

A launch reaches ``succeeded`` the moment its instruction is model-visible,
which is the right boundary for the launch plane: delivery is what the plane
controls. It is the wrong boundary for the operator who launched a worker
against a work item. A native that read its instruction, surveyed for nine
minutes, claimed nothing, said nothing, and was then reaped as claim-free
leaves a launch row reading ``succeeded`` while the item quietly returns to
the frontier — the one shape where the record and the outcome disagree.

So the end of a launch-created session is also the last moment to check
whether the worker ever participated. A work claim proves it entered the
mandate, and an outbound message makes a claim-free outcome visible to its
requester. Merely acknowledging the instruction or running a tool proves only
that the worker tried; a wrong first command followed by idle reaping must not
leave the launch claiming success.

Ending is not itself failure — a session that claimed, worked, and released
ends claim-free too. The distinguishing fact is that no claim row or outbound
message ever named this session, which no completed mandate can be true of.

A native that is killed never ends its session at all, so the same correction
also runs the moment the machine that started it proves the process is gone.
That check is stricter about what counts as having started: a completed tool
call is enough, because a worker that ran one was alive and working when it
died, and the launch is then an honest success that ended badly rather than a
worker that never began.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from yoke_core.domain.session_launch_store import (
    LAUNCH_COLUMNS,
    begin_mutation,
    marker,
    row_to_launch,
    update_launch,
    utc_now,
)
from yoke_core.domain.session_launch_types import LaunchRecord
from yoke_core.domain.session_relay_evidence import merge_redacted_evidence


_LOGGER = logging.getLogger(__name__)

ABANDONED_RESULT_CODE = "abandoned_without_claim"
NATIVE_PROCESS_GONE_REASON = "native_process_gone"
# Only a launch the plane calls successful can be wrong in this direction.
# One already closed as failed, expired, or uncertain is already honest.
_REVIEWABLE_STATES = frozenset({"succeeded"})


def _launch_for_session(conn: Any, session_id: str) -> LaunchRecord | None:
    """Return the launch that created this session, bound or not."""
    p = marker(conn)
    row = conn.execute(
        f"SELECT {LAUNCH_COLUMNS} FROM session_launches "
        f"WHERE registered_session_id = {p} OR native_session_id = {p} "
        "ORDER BY created_at DESC LIMIT 1",
        (session_id, session_id),
    ).fetchone()
    return row_to_launch(row) if row is not None else None


def _entered_mandate(
    conn: Any,
    session_id: str,
) -> bool:
    """Report whether work began or a claim-free outcome reached the requester."""
    p = marker(conn)
    claimed = conn.execute(
        f"SELECT 1 FROM work_claims WHERE session_id = {p} LIMIT 1",
        (session_id,),
    ).fetchone()
    if claimed is not None:
        return True
    spoke = conn.execute(
        f"SELECT 1 FROM session_messages WHERE sender_session_id = {p} LIMIT 1",
        (session_id,),
    ).fetchone()
    return spoke is not None


def _worked(conn: Any, session_id: str) -> bool:
    """Report whether this session ever performed an act only work performs.

    A completed tool call counts here and not at session end: a worker killed
    mid-tool-call was working, while one that ran a wrong first command and
    was then reaped idle was not.
    """
    p = marker(conn)
    if _entered_mandate(conn, session_id):
        return True
    ran = conn.execute(
        "SELECT 1 FROM events WHERE session_id = "
        + p
        + " AND event_name = 'HarnessToolCallCompleted' LIMIT 1",
        (session_id,),
    ).fetchone()
    return ran is not None


def settle_launch_native_death(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
    *,
    now: str | None = None,
) -> LaunchRecord | None:
    """Correct the launch of a worker whose native died before it ever worked.

    Runs from the relay's verified-death report, so it does not wait for the
    session to end — a killed native never ends its own session, which is
    exactly the shape that left a launch reading ``succeeded`` while its item
    quietly returned to the frontier.
    """
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = _launch_for_session(conn, session_id)
        if launch is None or launch.state not in _REVIEWABLE_STATES:
            conn.commit()
            return None
        if _worked(conn, session_id):
            conn.commit()
            return None
        tail = str(evidence.get("native_stderr_tail") or "").strip()
        reason = NATIVE_PROCESS_GONE_REASON
        if tail:
            reason = f"{NATIVE_PROCESS_GONE_REASON}: {tail}"
        recorded = {
            "result_code": ABANDONED_RESULT_CODE,
            "closure_reason": reason,
            "launch_phase_reached": "registered_and_injected",
            "registration_session_id": session_id,
            **{
                name: evidence[name]
                for name in (
                    "exit_code",
                    "native_diagnostic_ref",
                    "native_exit_at",
                    "native_stderr_tail",
                )
                if name in evidence
            },
        }
        flipped = update_launch(
            conn,
            launch.launch_id,
            delivery_changed_at=current,
            state="failed",
            completed_at=current,
            result_code=ABANDONED_RESULT_CODE,
            result_evidence=merge_redacted_evidence(launch.result_evidence, recorded),
        )
        conn.commit()
        return flipped
    except Exception:
        conn.rollback()
        raise


def settle_abandoned_launch(
    conn: Any,
    session_id: str,
    *,
    end_reason: str,
    now: str | None = None,
) -> LaunchRecord | None:
    """Fail the launch of a worker that ended without ever taking its mandate.

    Runs after the session end has committed, in its own transaction, and
    returns the flipped launch so the caller can notify whoever launched it.
    Returns ``None`` whenever there is nothing to correct, which is the
    ordinary case for every session a launch did not create.
    """
    current = now or utc_now()
    begin_mutation(conn)
    try:
        launch = _launch_for_session(conn, session_id)
        if launch is None or launch.state not in _REVIEWABLE_STATES:
            conn.commit()
            return None
        if _entered_mandate(conn, session_id):
            conn.commit()
            return None
        evidence = {
            "result_code": ABANDONED_RESULT_CODE,
            "closure_reason": str(end_reason or "session_ended")[:128],
            "launch_phase_reached": "registered_and_injected",
            "registration_session_id": session_id,
        }
        flipped = update_launch(
            conn,
            launch.launch_id,
            delivery_changed_at=current,
            state="failed",
            completed_at=current,
            result_code=ABANDONED_RESULT_CODE,
            result_evidence=merge_redacted_evidence(launch.result_evidence, evidence),
        )
        conn.commit()
        return flipped
    except Exception:
        conn.rollback()
        raise


def _stored_evidence(launch: LaunchRecord) -> dict[str, Any]:
    """Read a launch's evidence whether it is stored as JSON text or a map."""
    raw = launch.result_evidence
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        parsed = json.loads(raw or "")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def abandonment_notice(launch: LaunchRecord, session_id: str) -> str:
    """Render the sentence the launching session is told."""
    reason = str(_stored_evidence(launch).get("closure_reason") or "").strip()
    if reason.startswith(NATIVE_PROCESS_GONE_REASON):
        detail = reason[len(NATIVE_PROCESS_GONE_REASON) :].lstrip(": ").strip()
        said = f" Its last output was: {detail}" if detail else ""
        return (
            f"Launch {launch.launch_id} failed after delivery: the native "
            f"running session {session_id} is gone, and that session never "
            "acquired a work claim, sent a message, or completed a tool call, "
            f"so it never entered its mandate.{said} The launch is now recorded "
            f"{ABANDONED_RESULT_CODE}; whatever work it was given is unstarted."
        )
    return (
        f"Launch {launch.launch_id} failed after delivery: session {session_id} "
        "ended without ever acquiring a work claim or sending a message, so it "
        "never entered its mandate. The launch is now recorded "
        f"{ABANDONED_RESULT_CODE}; whatever work it was given is unstarted."
    )


def notify_launch_requester(
    conn: Any,
    launch: LaunchRecord,
    session_id: str,
) -> bool:
    """Tell the session that launched this worker that it never started.

    The launch row is the durable record; this is the part that reaches an
    orchestrator still waiting on a report it is never going to get.
    """
    requester = str(launch.requester_session_id or "").strip()
    if not requester:
        return False
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_message_service import send_message

    send_message(
        conn,
        actor_id=launch.requester_actor_id,
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[requester]),
        body=abandonment_notice(launch, session_id),
        idempotency_key=f"launch-abandoned:{launch.launch_id}",
        idempotency_intent_only=True,
    )
    return True


def settle_and_notify(
    conn: Any,
    session_id: str,
    *,
    end_reason: str,
) -> LaunchRecord | None:
    """Run the backstop around a committed session end, never raising.

    Session end is the caller's outcome, not this check's, so a control-plane
    hiccup here degrades to a launch row that stays optimistic rather than to
    a session that fails to end.
    """
    try:
        launch = settle_abandoned_launch(conn, session_id, end_reason=end_reason)
    except Exception:
        _LOGGER.debug("launch abandonment settle failed", exc_info=True)
        return None
    if launch is None:
        return None
    try:
        notify_launch_requester(conn, launch, session_id)
    except Exception:
        _LOGGER.debug("launch abandonment notice failed", exc_info=True)
    return launch


def settle_and_notify_native_death(
    conn: Any,
    session_id: str,
    evidence: Mapping[str, Any],
) -> LaunchRecord | None:
    """Run the death correction around a liveness report, never raising.

    The report's own outcome is the caller's, not this check's, so a failure
    here degrades to a launch row that stays optimistic rather than to a
    liveness poll that stops working.
    """
    try:
        launch = settle_launch_native_death(conn, session_id, evidence)
    except Exception:
        _LOGGER.debug("launch native-death settle failed", exc_info=True)
        return None
    if launch is None:
        return None
    try:
        notify_launch_requester(conn, launch, session_id)
    except Exception:
        _LOGGER.debug("launch abandonment notice failed", exc_info=True)
    return launch


__all__ = [
    "ABANDONED_RESULT_CODE",
    "NATIVE_PROCESS_GONE_REASON",
    "abandonment_notice",
    "notify_launch_requester",
    "settle_abandoned_launch",
    "settle_and_notify",
    "settle_and_notify_native_death",
    "settle_launch_native_death",
]
