"""A refused native wake reaches the seat without losing its original receipt."""

from __future__ import annotations

import json
from datetime import timedelta

from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt
from yoke_core.domain.steering_message_recipients import drainable_rows
from runtime.api.domain.test_session_message_support import (
    ACK_GRACE,
    NATIVE_WAKE_SESSION_ID,
    NOW,
    NOW_TEXT,
    message_connection,
    park_session,
    record_process_gone,
    selector,
)


SWEEP = NOW + timedelta(seconds=120)


def _parked_recipient(conn):
    park_session(conn)
    record_process_gone(conn, when=NOW + timedelta(seconds=60))
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (4,?,'item','{\"item_id\":101}',?)",
        (NATIVE_WAKE_SESSION_ID, NOW_TEXT),
    )
    conn.commit()
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s2",
        selector=selector(session_ids=[NATIVE_WAKE_SESSION_ID]),
        body="Continue the held work.",
        now=NOW,
    )["message_id"]


def _fail(conn, candidate, *, result="failed", reason="native_transcript_missing"):
    claim = claim_wake_attempt(conn, candidate=candidate, now=SWEEP.isoformat())
    assert claim is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code=?,evidence=? "
        "WHERE attempt_id=?",
        (
            SWEEP.isoformat(),
            result,
            json.dumps({"result_code": reason}),
            claim.attempt_id,
        ),
    )
    conn.commit()


def test_resume_refused_notifies_the_covering_document_seat_once() -> None:
    conn = message_connection()
    message_id = _parked_recipient(conn)
    conn.execute(
        "INSERT INTO item_strategy_docs VALUES (101,1,'AREA-PLAN',?)",
        (NOW_TEXT,),
    )
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (5,'s2','steering','{\"project_id\":1,\"document\":\"AREA-PLAN\"}',?)",
        (NOW_TEXT,),
    )
    conn.commit()
    _fail(conn, wake_eligible_recipients(conn, now=SWEEP)[0])
    wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=1))
    wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=2))
    notices = conn.execute(
        "SELECT m.body,r.seat_session_id,r.sender_item_id FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id=m.message_id "
        "WHERE r.recipient_kind='steering'",
    ).fetchall()
    assert len(notices) == 1
    assert "native_transcript_missing" in notices[0][0]
    assert message_id in notices[0][0]
    assert notices[0][1:] == ("s2", 101)
    original = conn.execute(
        "SELECT state,wake_attempt_count FROM session_message_recipients "
        "WHERE message_id=?",
        (message_id,),
    ).fetchone()
    assert tuple(original) == ("pending", 1)


def test_exhausted_retry_budget_parks_a_named_notice_for_the_next_seat() -> None:
    conn = message_connection()
    message_id = _parked_recipient(conn)
    _fail(conn, wake_eligible_recipients(conn, now=SWEEP)[0])
    conn.execute("UPDATE session_message_recipients SET wake_attempt_count=3")
    conn.commit()
    assert wake_eligible_recipients(conn, now=SWEEP + ACK_GRACE) == []
    rows = drainable_rows(conn, scope={"project_id": 1}, project_id=1)
    assert len(rows) == 1
    assert rows[0]["sender_item_id"] == 101
    assert "wake_attempts_exhausted" in rows[0]["body"]
    assert message_id in rows[0]["body"]


def test_failure_notices_do_not_recursively_generate_notices() -> None:
    conn = message_connection()
    _parked_recipient(conn)
    conn.execute(
        "INSERT INTO work_claims (id,session_id,target_kind,scope,claimed_at) "
        "VALUES (5,'s2','steering','{\"project_id\":1}',?)",
        (NOW_TEXT,),
    )
    conn.commit()
    _fail(conn, wake_eligible_recipients(conn, now=SWEEP)[0])
    wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=1))
    notice = conn.execute(
        "SELECT m.message_id FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id=m.message_id "
        "WHERE r.recipient_kind='steering'",
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,started_at,completed_at,"
        "result_code,evidence) VALUES ('notice-wake',?,'s2','wake_relay',?,?,'failed','{}')",
        (notice, SWEEP.isoformat(), SWEEP.isoformat()),
    )
    conn.commit()
    wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=2))
    assert conn.execute("SELECT COUNT(*) FROM session_messages").fetchone()[0] == 2
