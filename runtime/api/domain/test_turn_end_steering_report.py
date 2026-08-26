"""Turn-end report routing through live steering-scope claims."""

from __future__ import annotations

from yoke_contracts.session_control.models import RecipientSelector
from yoke_contracts.turn_end_evidence import REPORT_PAYLOAD_KEY, TurnEndReport
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.turn_end_steering_report import (
    ROUTED_REASON,
    evaluate,
    route_turn_end_report,
)
from yoke_core.domain.work_claim_targets import make_steering_target
from yoke_core.hooks.types import HookContext, Next, Outcome
from runtime.api.domain.test_session_message_support import (
    NOW,
    NOW_TEXT,
    message_connection,
)


def _connection():
    conn = message_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN actor_id INTEGER")
    conn.execute("UPDATE harness_sessions SET actor_id=10")
    target = make_steering_target(1)
    conn.execute(
        "INSERT INTO work_claims "
        "(id,session_id,target_kind,scope,claimed_at) VALUES (4,'s2',?,?,?)",
        (target.kind, target.scope_json(), NOW_TEXT),
    )
    conn.commit()
    return conn


def _report(label: str) -> TurnEndReport:
    return TurnEndReport(body=f"Report {label}.", fingerprint=f"turn-{label}")


def _message_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0])


def _record_launch_attempt(conn, session_id: str) -> None:
    launch_message = send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=RecipientSelector(session_ids=[session_id]),
        body="Launch instruction.",
        now=NOW,
    )
    conn.execute(
        "INSERT INTO session_launches "
        "(launch_id,requester_actor_id,requester_session_id,project_id,"
        "requested_surface,selected_surface,message_id,state,deadline_at,created_at) "
        "VALUES ('launch-1',10,'s2',1,'codex-desktop','codex-desktop',?,"
        "'succeeded',?,?)",
        (launch_message["message_id"], NOW_TEXT, NOW_TEXT),
    )
    conn.execute(
        "INSERT INTO session_launch_attempts "
        "(attempt_id,launch_id,machine_id,lease_id,attempt_number,started_at,"
        "completed_at,native_session_id,result_code) "
        "VALUES ('attempt-1','launch-1','m1','lease-1',1,?,?,?,'native_created')",
        (NOW_TEXT, NOW_TEXT, session_id),
    )
    conn.commit()


def test_covered_operator_session_routes_to_steering_holder() -> None:
    conn = _connection()

    routed = route_turn_end_report(
        conn, session_id="s1", report=_report("covered"), now=NOW
    )
    duplicate = route_turn_end_report(
        conn, session_id="s1", report=_report("covered"), now=NOW
    )

    assert routed is not None
    assert routed["recipient_session_id"] == "s2"
    assert duplicate is not None
    assert duplicate["deduplicated"] is True
    assert _message_count(conn) == 1
    message = conn.execute("SELECT * FROM session_messages").fetchone()
    receipt = conn.execute("SELECT * FROM session_message_recipients").fetchone()
    assert message["sender_session_id"] == "s1"
    assert message["body"] == "Report covered."
    assert receipt["session_id"] == "s2"
    assert receipt["state"] == "pending"


def test_uncovered_operator_session_keeps_operator_delivery() -> None:
    conn = _connection()
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=4", (NOW_TEXT,))
    conn.commit()

    routed = route_turn_end_report(
        conn, session_id="s1", report=_report("uncovered"), now=NOW
    )

    assert routed is None
    assert _message_count(conn) == 0


def test_launch_provenance_never_redirects_worker_report() -> None:
    conn = _connection()
    _record_launch_attempt(conn, "s1")
    before = _message_count(conn)

    routed = route_turn_end_report(
        conn, session_id="s1", report=_report("launched"), now=NOW
    )

    assert routed is None
    assert _message_count(conn) == before


def test_released_claim_makes_next_report_fall_back_without_rerouting() -> None:
    conn = _connection()
    first = route_turn_end_report(
        conn, session_id="s1", report=_report("first"), now=NOW
    )
    assert first is not None
    conn.execute("UPDATE work_claims SET released_at=? WHERE id=4", (NOW_TEXT,))
    conn.commit()

    second = route_turn_end_report(
        conn, session_id="s1", report=_report("second"), now=NOW
    )

    assert second is None
    assert _message_count(conn) == 1
    receipt = conn.execute("SELECT state FROM session_message_recipients").fetchone()
    assert receipt["state"] == "pending"


def test_successful_route_ends_stop_chain_without_waiting(monkeypatch) -> None:
    class Connection:
        def close(self) -> None:
            pass

    monkeypatch.setattr("yoke_core.domain.db_helpers.connect", lambda: Connection())
    monkeypatch.setattr(
        "yoke_core.domain.turn_end_steering_report.route_turn_end_report",
        lambda *args, **kwargs: {
            "message_id": "message-1",
            "recipient_session_id": "s2",
        },
    )
    report = _report("stop")
    decision = evaluate(
        HookContext(
            event_name="Stop",
            executor_family="codex",
            executor_surface="codex-desktop",
            payload={REPORT_PAYLOAD_KEY: report.as_dict()},
            session_id="s1",
            remote=True,
            now=NOW,
        )
    )

    assert decision.outcome is Outcome.ALLOW
    assert decision.next is Next.STOP
    assert decision.audit_fields["reason"] == ROUTED_REASON
