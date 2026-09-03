"""A relayed stop is mailed only when its body names something to act on."""

from __future__ import annotations

import json

from yoke_contracts.session_control.launch_origin import LAUNCH_ORIGIN_STEERING
from yoke_contracts.turn_end_evidence import REPORT_PAYLOAD_KEY, TurnEndReport
from yoke_core.domain.turn_end_steering_report import (
    EVENT_STEERING_REPORT_SKIPPED,
    SKIPPED_REASON,
    evaluate,
    route_turn_end_report,
)
from yoke_core.hooks.types import HookContext, Next, Outcome
from runtime.api.domain.test_session_message_support import NOW
from runtime.api.domain.test_turn_end_steering_report import (
    _connection,
    _message_count,
    _record_launch,
)


def _wait_report(label: str) -> TurnEndReport:
    """A stop body that names nothing the seat would do anything about."""
    return TurnEndReport(body=f"Waiting on the {label}.", fingerprint=f"turn-{label}")


def _skip_events(conn) -> list:
    return conn.execute(
        "SELECT * FROM events WHERE event_name=?",
        (EVENT_STEERING_REPORT_SKIPPED,),
    ).fetchall()


def test_a_stop_with_nothing_to_act_on_is_recorded_instead_of_mailed() -> None:
    """A wait note costs the seat an acknowledgement and changes nothing."""
    conn = _connection()
    _record_launch(conn, "s1", LAUNCH_ORIGIN_STEERING)
    before = _message_count(conn)

    skipped = route_turn_end_report(
        conn, session_id="s1", report=_wait_report("sweep"), now=NOW
    )

    assert skipped is not None
    assert skipped["skipped"] is True
    assert skipped["reason"] == SKIPPED_REASON
    assert skipped["recipient_session_id"] == "s2"
    assert _message_count(conn) == before

    events = _skip_events(conn)
    assert len(events) == 1
    context = json.loads(events[0]["envelope"])["context"]
    assert events[0]["session_id"] == "s1"
    assert context["recipient_session_id"] == "s2"
    assert context["body_excerpt"] == "Waiting on the sweep."
    assert context["body_chars"] == len("Waiting on the sweep.")
    assert context["fingerprint"] == "turn-sweep"
    assert context["reason"] == SKIPPED_REASON


def test_a_substantive_stop_still_reaches_the_seat_unchanged() -> None:
    """The floor removes the wait notes, not the reports."""
    conn = _connection()
    _record_launch(conn, "s1", LAUNCH_ORIGIN_STEERING)
    before = _message_count(conn)

    routed = route_turn_end_report(
        conn,
        session_id="s1",
        report=TurnEndReport(
            body="The QA gate went red: test_relay.py::test_skip FAILED.",
            fingerprint="turn-red",
        ),
        now=NOW,
    )

    assert routed is not None
    assert routed["recipient_session_id"] == "s2"
    assert _message_count(conn) == before + 1
    assert _skip_events(conn) == []


def test_a_skipped_stop_leaves_the_rest_of_the_chain_to_run(monkeypatch) -> None:
    """Nothing was mailed, so the Stop chain still owns this turn."""

    class Connection:
        def close(self) -> None:
            pass

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: Connection())
    monkeypatch.setattr(
        "yoke_core.domain.turn_end_steering_report.route_turn_end_report",
        lambda *args, **kwargs: {
            "skipped": True,
            "reason": SKIPPED_REASON,
            "recipient_session_id": "s2",
        },
    )
    decision = evaluate(
        HookContext(
            event_name="Stop",
            executor_family="codex",
            executor_surface="codex-desktop",
            payload={REPORT_PAYLOAD_KEY: _wait_report("run").as_dict()},
            session_id="s1",
            remote=True,
            now=NOW,
        )
    )

    assert decision.outcome is Outcome.AUDIT_ONLY
    assert decision.next is Next.CONTINUE
    assert decision.audit_fields["reason"] == SKIPPED_REASON
    assert decision.audit_fields["recipient_session_id"] == "s2"
