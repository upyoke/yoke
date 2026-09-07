"""What the relay's sweep does with a session it decided is owed a resume.

The state reader's answers are asserted next door; these cases are about
the acting: that the resumed worker is told what happened and where to
pick up, that the row says which client build served the retry — the
incident was cured by a client update mid-outage — and that a wake the
delivery path refuses costs the session nothing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from runtime.api.domain.session_vendor_error_test_support import (
    INSTALLED_VERSION,
    MACHINE_ID,
    PROJECT_ID,
    SESSION_ID,
    SESSION_VERSION,
    TURN_ENDED_AT,
    observe_turn_end,
    one_state,
    worker_connection,
)
from yoke_core.domain.session_vendor_error_resume import (
    EVENT_SESSION_VENDOR_ERROR_RESUMED,
    resume_vendor_error_sessions,
)


def _resume(conn, monkeypatch, *, now: datetime, fail: Exception | None = None):
    """Run the sweep with the wake path stubbed, capturing what it was told."""
    from yoke_core.domain import session_manual_wake

    sent: list[dict] = []

    def _fake_wake(_conn, **kwargs):
        sent.append(kwargs)
        if fail is not None:
            raise fail
        return {"message_id": "wake-1"}

    monkeypatch.setattr(session_manual_wake, "request_session_wake", _fake_wake)
    outcome = resume_vendor_error_sessions(
        conn,
        machine_id=MACHINE_ID,
        authorized_projects=(PROJECT_ID,),
        actor_id=1,
        now=now,
    )
    return outcome, sent


def test_a_due_resume_names_the_failure_and_where_to_continue(monkeypatch):
    conn = worker_connection()
    observe_turn_end(conn)

    outcome, sent = _resume(
        conn, monkeypatch, now=TURN_ENDED_AT + timedelta(seconds=90)
    )

    assert outcome["resumed"] == [SESSION_ID]
    assert len(sent) == 1
    prompt = sent[0]["prompt"]
    assert "404 Not Found" in prompt
    assert "last committed state" in prompt
    assert "attempt 1 of 3" in prompt


def test_a_resume_stamps_the_client_version_installed_now(monkeypatch):
    """The build was swapped under the fleet mid-incident; the row must say so."""
    conn = worker_connection()
    observe_turn_end(conn)

    _resume(conn, monkeypatch, now=TURN_ENDED_AT + timedelta(seconds=90))

    recorded = conn.execute(
        "SELECT envelope FROM events WHERE event_name=?",
        (EVENT_SESSION_VENDOR_ERROR_RESUMED,),
    ).fetchone()
    context = json.loads(recorded["envelope"])["context"]
    assert context["executor_version"] == INSTALLED_VERSION
    assert context["previous_executor_version"] == SESSION_VERSION
    assert context["attempt"] == 1
    assert context["signature_id"] == "client_refused"
    # The session now runs that binary, so version-gated routing must read it.
    assert (
        conn.execute(
            "SELECT executor_version FROM harness_sessions WHERE session_id=?",
            (SESSION_ID,),
        ).fetchone()["executor_version"]
        == INSTALLED_VERSION
    )


def test_a_refused_wake_is_named_and_costs_no_attempt(monkeypatch):
    from yoke_core.domain.session_message_types import SessionMessageError

    conn = worker_connection()
    observe_turn_end(conn)

    outcome, _ = _resume(
        conn,
        monkeypatch,
        now=TURN_ENDED_AT + timedelta(seconds=90),
        fail=SessionMessageError("wake_in_flight", "another wake is settling"),
    )

    assert outcome["resumed"] == []
    assert outcome["refused"] == [
        {
            "session_id": SESSION_ID,
            "status": "wake_in_flight",
            "detail": "another wake is settling",
        }
    ]
    # Nothing reached the session, so the next poll owes the same attempt.
    assert one_state(conn, now=TURN_ENDED_AT + timedelta(seconds=120))["attempts"] == 0


def test_a_crash_after_the_wake_does_not_refund_the_attempt(monkeypatch) -> None:
    """The attempt is reserved before the wake, so a lost caller still pays.

    Counting resumes by their emitted telemetry meant a poller that died
    after waking — or a dropped emission — gave the budget back, which is
    exactly the unbounded retry against a provider wall the budget exists
    to stop.
    """
    conn = worker_connection()
    observe_turn_end(conn)

    class _CrashedAfterWaking(RuntimeError):
        pass

    def _wake_then_die(_conn, **_kwargs):
        raise _CrashedAfterWaking("the poller died holding the reservation")

    from yoke_core.domain import session_manual_wake

    monkeypatch.setattr(session_manual_wake, "request_session_wake", _wake_then_die)
    try:
        resume_vendor_error_sessions(
            conn,
            machine_id=MACHINE_ID,
            authorized_projects=(PROJECT_ID,),
            actor_id=1,
            now=TURN_ENDED_AT + timedelta(seconds=90),
        )
    except _CrashedAfterWaking:
        pass

    later = one_state(conn, now=TURN_ENDED_AT + timedelta(minutes=30))
    assert later["attempts"] == 1


def test_the_budget_survives_a_database_with_no_events_at_all(monkeypatch) -> None:
    """Expiry is the ordinary case, so recovery must not read the ledger."""
    conn = worker_connection()
    observe_turn_end(conn)
    conn.execute("DELETE FROM events")
    conn.commit()

    outcome, sent = _resume(
        conn,
        monkeypatch,
        now=TURN_ENDED_AT + timedelta(seconds=90),
    )

    assert outcome["resumed"] == [SESSION_ID]
    assert len(sent) == 1
    assert one_state(conn, now=TURN_ENDED_AT + timedelta(minutes=30))["attempts"] == 1
