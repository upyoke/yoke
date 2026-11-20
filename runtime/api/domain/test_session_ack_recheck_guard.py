"""Acknowledging a QA recheck wake owes the next recheck, as a park does."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import HOLDER_A
from runtime.api.domain.test_session_park_recheck_guard import (
    REQUIREMENT,
    _schedule,
    _seed,
)
from yoke_contracts.session_control.recipient_selector import RecipientSelector
from yoke_contracts.session_control.wake_instruction import native_wake_instruction
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_qa_manual_notice import MANUAL_WAIT_PREFIX
from yoke_core.domain.session_message_receipts import acknowledge_message
from yoke_core.domain.session_message_types import SessionMessageError
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_scheduled_wake import enqueue_due_session_wakes


def _notice_id(conn: Any) -> str:
    [row] = conn.execute(
        "SELECT message_id FROM session_messages WHERE idempotency_key LIKE %s",
        (f"{MANUAL_WAIT_PREFIX}{REQUIREMENT}:{HOLDER_A}:%",),
    ).fetchall()
    return str(row[0])


def _state(conn: Any, message_id: str) -> str:
    return str(
        conn.execute(
            "SELECT state FROM session_message_recipients "
            "WHERE message_id=%s AND session_id=%s",
            (message_id, HOLDER_A),
        ).fetchone()[0]
    )


def test_manual_wait_ack_without_a_future_recheck_is_refused(test_db: Any) -> None:
    _seed(test_db)
    message_id = _notice_id(test_db)
    with pytest.raises(SessionMessageError) as refused:
        acknowledge_message(test_db, message_id=message_id, session_id=HOLDER_A)
    assert refused.value.code == "PARK_RECHECK_REQUIRED"
    text = str(refused.value)
    assert f"requirement #{REQUIREMENT}" in text
    assert "yoke sessions wake schedule --at UTC_INSTANT --reason" in text
    assert "then acknowledge again" in text
    assert _state(test_db, message_id) != "acknowledged"


def test_manual_wait_ack_succeeds_after_scheduling(test_db: Any) -> None:
    _seed(test_db)
    message_id = _notice_id(test_db)
    _schedule(test_db)
    acknowledge_message(test_db, message_id=message_id, session_id=HOLDER_A)
    assert _state(test_db, message_id) == "acknowledged"


def test_fired_scheduled_wake_ack_owes_the_next_recheck(test_db: Any) -> None:
    _seed(test_db)
    _schedule(test_db, hours=1)
    assert enqueue_due_session_wakes(test_db, now=utc_now() + timedelta(hours=2)) == 1
    test_db.commit()
    [row] = test_db.execute(
        "SELECT message_id FROM session_messages WHERE idempotency_key LIKE %s",
        ("scheduled-wake:%",),
    ).fetchall()
    with pytest.raises(SessionMessageError, match="no future scheduled recheck"):
        acknowledge_message(test_db, message_id=str(row[0]), session_id=HOLDER_A)


def test_ordinary_message_acknowledges_despite_the_open_obligation(
    test_db: Any,
) -> None:
    _seed(test_db)
    actor = test_db.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
    ).fetchone()[0]
    sent = send_message(
        test_db,
        actor_id=int(actor),
        sender_session_id=None,
        engine_sender=True,
        selector=RecipientSelector(session_ids=[HOLDER_A]),
        body="an ordinary steering ask",
    )
    test_db.commit()
    message_id = str(sent["message_id"])
    acknowledge_message(test_db, message_id=message_id, session_id=HOLDER_A)
    assert _state(test_db, message_id) == "acknowledged"


def test_wake_instruction_drops_the_needs_none_escape_for_rechecks() -> None:
    instruction = native_wake_instruction("message-1")
    assert "A QA recheck or scheduled wake never needs none" in instruction
    assert "yoke sessions wake schedule --at UTC_INSTANT --reason TEXT" in instruction
