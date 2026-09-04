"""A delivered launch whose worker never took hold is recorded as failed."""

from __future__ import annotations

import json
from dataclasses import replace

from yoke_core.domain import session_launch_abandonment as launch_abandonment
from yoke_core.domain.session_launch_abandonment import (
    ABANDONED_RESULT_CODE,
    abandonment_notice,
    notify_launch_requester,
    settle_abandoned_launch,
    settle_and_notify,
)
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_registration import (
    complete_launch_injection,
    prepare_launch_registration,
)
from yoke_core.domain.session_launch_store import get_launch
from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    launch_connection,
)
from runtime.api.domain.test_session_message_support import message_connection


WORKER = "session-worker"


def _worker_tables(conn) -> None:
    """Add the work and activity state read by the abandonment backstop."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            released_at TEXT
        )"""
    )
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN last_tool_call_at TEXT")
    conn.execute(
        "ALTER TABLE harness_sessions ADD COLUMN tool_call_count "
        "INTEGER NOT NULL DEFAULT 0"
    )
    conn.commit()


def _capture_notifications(monkeypatch) -> list[tuple[str, str]]:
    notifications: list[tuple[str, str]] = []

    def record_notification(_conn, launch, session_id) -> bool:
        notifications.append((launch.launch_id, session_id))
        return True

    monkeypatch.setattr(
        launch_abandonment,
        "notify_launch_requester",
        record_notification,
    )
    return notifications


def _delivered_launch(conn, *, key: str = "mandate"):
    """Drive one launch all the way to succeeded, as a real worker does."""
    launch = assigned_launch(conn, key=key)
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )
    report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="native_created",
        native_session_id=WORKER,
        now="2026-08-22T12:00:30Z",
    )
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, project_id, executor_surface, executor_version, "
        "machine_id, model) VALUES (?, 10, 'codex-cli', '0.148.0a15', "
        "'machine-1', 'gpt-5')",
        (WORKER,),
    )
    conn.commit()
    prepare_launch_registration(
        conn,
        launch_id=launch.launch_id,
        attestation=claim.attestation,
        session_id=WORKER,
        now="2026-08-22T12:00:31Z",
    )
    conn.execute(
        "UPDATE session_message_recipients SET state='injected' "
        "WHERE message_id=? AND session_id=?",
        (launch.message_id, WORKER),
    )
    conn.commit()
    return complete_launch_injection(
        conn,
        launch_id=launch.launch_id,
        session_id=WORKER,
        injected=True,
        now="2026-08-22T12:00:32Z",
    )


def test_worker_that_ended_without_claiming_flips_its_launch() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    delivered = _delivered_launch(conn)
    assert delivered.state == "succeeded"

    flipped = settle_abandoned_launch(
        conn,
        WORKER,
        end_reason="session_empty_auto_ended",
        now="2026-08-22T12:09:00Z",
    )

    assert flipped is not None
    assert flipped.state == "failed"
    assert flipped.result_code == ABANDONED_RESULT_CODE
    assert flipped.completed_at == "2026-08-22T12:09:00Z"
    evidence = json.loads(flipped.result_evidence)
    assert evidence["result_code"] == ABANDONED_RESULT_CODE
    assert evidence["closure_reason"] == "session_empty_auto_ended"
    assert evidence["registration_session_id"] == WORKER


def test_worker_that_held_a_claim_keeps_its_successful_launch() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    _delivered_launch(conn)
    conn.execute(
        "INSERT INTO work_claims (session_id, released_at) VALUES (?, ?)",
        (WORKER, "2026-08-22T12:08:00Z"),
    )
    conn.commit()

    assert (
        settle_abandoned_launch(conn, WORKER, end_reason="session_ended", now=NOW)
        is None
    )


def test_worker_that_acknowledged_and_ran_a_tool_without_claiming_is_reported(
    monkeypatch,
) -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    launch = _delivered_launch(conn)
    notifications = _capture_notifications(monkeypatch)
    conn.execute(
        "UPDATE session_message_recipients "
        "SET state='acknowledged', acknowledged_at=? "
        "WHERE message_id=? AND session_id=?",
        (NOW, launch.message_id, WORKER),
    )
    conn.execute(
        "UPDATE harness_sessions "
        "SET last_tool_call_at=?, tool_call_count=1 WHERE session_id=?",
        (NOW, WORKER),
    )
    conn.commit()

    flipped = settle_and_notify(conn, WORKER, end_reason="session_empty_auto_ended")

    assert flipped is not None
    assert flipped.result_code == ABANDONED_RESULT_CODE
    assert get_launch(conn, launch.launch_id).state == "failed"
    assert notifications == [(launch.launch_id, WORKER)]


def test_worker_that_reported_to_its_orchestrator_keeps_its_launch() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    _delivered_launch(conn)
    conn.execute(
        "INSERT INTO session_messages "
        "(message_id, sender_actor_id, sender_session_id, body, body_sha256, "
        "selector_snapshot, created_at, expires_at) "
        "VALUES ('report-1', 1, ?, 'done', 'sha', '{}', ?, ?)",
        (WORKER, NOW, NOW),
    )
    conn.commit()

    assert (
        settle_abandoned_launch(conn, WORKER, end_reason="session_ended", now=NOW)
        is None
    )


def test_silent_worker_notifies_requester_of_abandonment(monkeypatch) -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    launch = _delivered_launch(conn)
    notifications = _capture_notifications(monkeypatch)

    flipped = settle_and_notify(
        conn,
        WORKER,
        end_reason="session_empty_auto_ended",
    )

    assert flipped is not None
    assert flipped.result_code == ABANDONED_RESULT_CODE
    assert notifications == [(launch.launch_id, WORKER)]


def test_launch_already_closed_as_failed_is_left_alone() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    launch = _delivered_launch(conn)
    conn.execute(
        "UPDATE session_launches SET state='failed', result_code='late_registration' "
        "WHERE launch_id=?",
        (launch.launch_id,),
    )
    conn.commit()

    assert (
        settle_abandoned_launch(conn, WORKER, end_reason="session_ended", now=NOW)
        is None
    )
    assert get_launch(conn, launch.launch_id).result_code == "late_registration"


def test_session_no_launch_created_is_not_touched() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    _delivered_launch(conn)

    assert (
        settle_abandoned_launch(conn, "unrelated", end_reason="session_ended", now=NOW)
        is None
    )


def test_notice_names_the_launch_and_the_session_that_never_started() -> None:
    conn = launch_connection()
    _worker_tables(conn)
    add_relay(conn)
    launch = _delivered_launch(conn)

    notice = abandonment_notice(launch, WORKER)

    assert launch.launch_id in notice
    assert WORKER in notice
    assert ABANDONED_RESULT_CODE in notice


def test_repeated_abandonment_notice_accepts_a_reworded_body() -> None:
    launch_conn = launch_connection()
    add_relay(launch_conn)
    launch = assigned_launch(launch_conn)
    conn = message_connection()
    first = replace(
        launch,
        requester_actor_id=10,
        requester_session_id="s1",
        project_id=1,
        result_evidence=json.dumps({"closure_reason": "session_ended"}),
    )
    reworded = replace(
        first,
        result_evidence=json.dumps(
            {"closure_reason": "native_process_gone: process exited 1"}
        ),
    )
    assert abandonment_notice(first, WORKER) != abandonment_notice(reworded, WORKER)

    assert notify_launch_requester(conn, first, WORKER)
    assert notify_launch_requester(conn, reworded, WORKER)

    rows = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key=?",
        (f"launch-abandoned:{launch.launch_id}",),
    ).fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == abandonment_notice(first, WORKER)
