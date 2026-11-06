# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import timedelta

import pytest

from yoke_core.domain.session_message_service import send_message

from yoke_core.domain.session_message_wake import wake_eligible_recipients

from yoke_core.domain.session_message_receipts import acknowledge_message

from yoke_core.domain.session_wake_failure_notice import notify_failed_wake

from yoke_core.domain.session_relay_wake_claim import claim_wake_attempt

from yoke_contracts.session_control.wake_delivery import NATIVE_TURN_RUNNING_RESULT

from yoke_core.domain.steering_message_recipients import drainable_rows

from runtime.api.domain.session_message_support_test_support import (
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


def _fail(
    conn,
    candidate,
    *,
    result="failed",
    reason="native_transcript_missing",
    skip_reason=None,
):
    claim = claim_wake_attempt(conn, candidate=candidate, now=SWEEP.isoformat())
    assert claim is not None
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=?,result_code=?,evidence=? "
        "WHERE attempt_id=?",
        (
            SWEEP.isoformat(),
            result,
            json.dumps({"result_code": reason, "skip_reason": skip_reason}),
            claim.attempt_id,
        ),
    )
    conn.commit()
