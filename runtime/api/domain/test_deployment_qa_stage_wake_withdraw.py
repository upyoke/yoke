"""A deployment QA wait wake does not outlive its settled subject.

The live failure was a pending wait for a run that had already succeeded
and a member that was already done: every retry still instructed work
that needed no crediting. These cover that pair — the wake is withdrawn
by the event that settles it, and already-recorded attempts stay as
evidence. Receipt expiry never re-evaluates waits.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
    _claim,
    _project,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
    run_stage_wait_idempotency_key,
    stage_wait_idempotency_key,
)
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
)
from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
    withdraw_deployment_qa_wait_wakes,
)
from yoke_core.domain.item_terminal_resources import release_for_terminal_transition
from yoke_core.domain.session_message_delivery import expire_due_recipients
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_contracts.timestamps import parse_instant


RUN_ID = "run-20260920-011"
STAGE = "item-qa"
MEMBER_A = 9706
MEMBER_B = 9707
NOW = datetime(2026, 9, 21, 3, 12, tzinfo=timezone.utc)


def _message(conn: Any, key: str) -> tuple[str, datetime | None, str]:
    row = conn.execute(
        "SELECT message_id, cancelled_at, "
        "COALESCE(cancellation_reason,'') FROM session_messages "
        "WHERE idempotency_key=%s",
        (key,),
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1], str(row[2])


def _recipient_state(conn: Any, message_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM session_message_recipients WHERE message_id=%s",
        (message_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _seed_member(
    conn: Any, item_id: int, session_id: str, *, status: str = "idea"
) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        status=status,
    )
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )


def _wait(conn: Any, item_id: int) -> str:
    result = notify_item_scoped_qa_wait(
        conn,
        run_id=RUN_ID,
        stage_name=STAGE,
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
    )
    assert result in ("delivered", "undelivered")
    return stage_wait_idempotency_key(RUN_ID, STAGE, item_id)


def _executing_run(conn: Any) -> None:
    insert_deployment_run(
        conn,
        id=RUN_ID,
        project_id=PROJECT_YOKE,
        status="executing",
        current_stage=STAGE,
    )


def test_a_wait_wake_does_not_survive_the_run_completing(test_db: Any) -> None:
    """The measured failure: run succeeded, member done, wait still pending."""
    _project(test_db)
    _seed_member(test_db, MEMBER_A, HOLDER_A)
    _executing_run(test_db)
    key = _wait(test_db, MEMBER_A)
    message_id, cancelled_at, _reason = _message(test_db, key)
    test_db.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,"
        "started_at,completed_at,result_code) "
        "VALUES (%s,%s,%s,'wake_relay',%s,%s,%s)",
        (
            "attempt-stale-1",
            message_id,
            HOLDER_A,
            "2026-09-20T21:55:00Z",
            "2026-09-20T21:55:01Z",
            "native_turn_running",
        ),
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded', current_stage='complete' "
        "WHERE id=%s",
        (RUN_ID,),
    )
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (MEMBER_A,))
    test_db.commit()
    assert cancelled_at is None
    assert _recipient_state(test_db, message_id) == "pending"

    withdrawn = withdraw_deployment_qa_wait_wakes(
        test_db, run_id=RUN_ID, reason="run_terminal:succeeded", now=NOW
    )

    assert withdrawn == 1
    _, cancelled_at, reason = _message(test_db, key)
    assert cancelled_at == NOW
    assert reason == "run_terminal:succeeded"
    assert _recipient_state(test_db, message_id) == "cancelled"
    attempt = test_db.execute(
        "SELECT result_code, completed_at FROM session_message_attempts "
        "WHERE attempt_id=%s",
        ("attempt-stale-1",),
    ).fetchone()
    assert str(attempt[0]) == "native_turn_running"
    assert attempt[1] == parse_instant("2026-09-20T21:55:01Z")


def test_receipt_expiry_leaves_waits_to_their_settling_event(test_db: Any) -> None:
    _project(test_db)
    _seed_member(test_db, MEMBER_A, HOLDER_A)
    _executing_run(test_db)
    key = _wait(test_db, MEMBER_A)
    test_db.execute("UPDATE deployment_runs SET status='failed' WHERE id=%s", (RUN_ID,))
    test_db.commit()

    # Receipt expiry runs inside acknowledge and relay claim: it never
    # re-reads a wait's subject, even one that is settled.
    assert expire_due_recipients(test_db, now=NOW) == 0
    message_id, cancelled_at, reason = _message(test_db, key)
    assert cancelled_at is None
    assert reason == ""
    assert _recipient_state(test_db, message_id) == "pending"


def test_a_done_member_loses_its_wait_while_the_run_is_still_live(
    test_db: Any,
) -> None:
    _project(test_db)
    _seed_member(test_db, MEMBER_A, HOLDER_A)
    _seed_member(test_db, MEMBER_B, HOLDER_B)
    _executing_run(test_db)
    key_a = _wait(test_db, MEMBER_A)
    key_b = _wait(test_db, MEMBER_B)
    test_db.execute("UPDATE items SET status='done' WHERE id=%s", (MEMBER_A,))

    release_for_terminal_transition(
        test_db, item_id=MEMBER_A, target_status="done", session_id=None, actor_id=None
    )
    test_db.commit()

    _, cancelled_a, reason_a = _message(test_db, key_a)
    _, cancelled_b, reason_b = _message(test_db, key_b)
    assert cancelled_a is not None
    assert reason_a == "member_done"
    assert cancelled_b is None
    assert reason_b == ""


def test_a_run_scoped_wait_withdraws_when_the_run_is_terminal(test_db: Any) -> None:
    _project(test_db)
    seed_session(test_db, HOLDER_A)
    _executing_run(test_db)
    attach_driver(test_db, RUN_ID, session_id=HOLDER_A, pid=4242, phase=PHASE_EXECUTING)
    test_db.commit()
    result = notify_run_scoped_qa_wait(
        test_db,
        run_id=RUN_ID,
        stage_name=STAGE,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
    )
    assert result in ("delivered", "undelivered")
    key = run_stage_wait_idempotency_key(RUN_ID, STAGE)
    assert (
        withdraw_deployment_qa_wait_wakes(
            test_db, run_id=RUN_ID, reason="run_terminal:failed", now=NOW
        )
        == 1
    )
    _, cancelled_at, reason = _message(test_db, key)
    assert cancelled_at == NOW
    assert reason == "run_terminal:failed"


def test_withdraw_is_a_no_op_when_the_message_plane_is_absent() -> None:
    """Terminal run updates still happen on lean DBs with no Fleet tables."""
    conn = sqlite3.connect(":memory:")
    assert (
        withdraw_deployment_qa_wait_wakes(
            conn, run_id="run-lean", reason="run_terminal:failed"
        )
        == 0
    )
