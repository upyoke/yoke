"""A delivered launch whose worker never took hold is recorded as failed."""

from __future__ import annotations

import json

from yoke_core.domain.session_launch_abandonment import (
    ABANDONED_RESULT_CODE,
    abandonment_notice,
    settle_abandoned_launch,
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


WORKER = "session-worker"


def _worker_tables(conn) -> None:
    """Add the two tables the backstop reads; messages come with the fixture."""
    conn.execute(
        """CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            released_at TEXT
        )"""
    )
    conn.commit()


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
