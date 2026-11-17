"""A wake the relay handed back busy or stopping is deferred, not failed.

The relay releases an unstarted wake with result ``released`` and its reason
in evidence; the next claim delivers it. Only a spent wake budget notifies.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from runtime.api.domain.session_message_support_test_support import (
    ACK_GRACE,
    message_connection,
)
from runtime.api.domain.session_wake_failure_notice_test_support import (
    SWEEP,
    _fail,
    _parked_recipient,
)
from yoke_contracts.session_control.wake_delivery import (
    RELAY_STOPPING,
    RELAY_WORKERS_BUSY,
    RELEASED_RESULT,
    delivery_attempt_diagnostic,
    delivery_attempt_failed,
)
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.steering_message_recipients import drainable_rows


@pytest.mark.parametrize("reason", [RELAY_WORKERS_BUSY, RELAY_STOPPING])
def test_handed_back_wake_is_not_a_failed_attempt(reason) -> None:
    evidence = {"result_code": reason}
    assert delivery_attempt_failed(RELEASED_RESULT, evidence) is False
    assert delivery_attempt_diagnostic(RELEASED_RESULT, evidence) == ""


def test_other_release_reasons_still_fail() -> None:
    evidence = {"result_code": "relay_adapter_refused"}
    assert delivery_attempt_failed(RELEASED_RESULT, evidence) is True
    assert delivery_attempt_diagnostic(RELEASED_RESULT, evidence) == "relay_adapter_refused"


def _notices(conn, message_id):
    return conn.execute(
        "SELECT count(*) FROM session_messages WHERE message_id<>?", (message_id,)
    ).fetchone()[0]


@pytest.mark.parametrize("reason", [RELAY_WORKERS_BUSY, RELAY_STOPPING])
def test_sweep_after_a_hand_back_posts_no_failure_notice(reason) -> None:
    conn = message_connection()
    message_id = _parked_recipient(conn)
    _fail(
        conn,
        wake_eligible_recipients(conn, now=SWEEP)[0],
        result=RELEASED_RESULT,
        reason=reason,
    )

    wake_eligible_recipients(conn, now=SWEEP + timedelta(seconds=15))
    wake_eligible_recipients(conn, now=SWEEP + ACK_GRACE)

    assert _notices(conn, message_id) == 0


def test_an_exhausted_budget_after_a_hand_back_still_notifies() -> None:
    conn = message_connection()
    message_id = _parked_recipient(conn)
    _fail(
        conn,
        wake_eligible_recipients(conn, now=SWEEP)[0],
        result=RELEASED_RESULT,
        reason=RELAY_WORKERS_BUSY,
    )
    conn.execute("UPDATE session_message_recipients SET wake_attempt_count=3")
    conn.commit()

    assert wake_eligible_recipients(conn, now=SWEEP + ACK_GRACE) == []

    rows = drainable_rows(conn, scope={"project_id": 1}, project_id=1, now=SWEEP)
    assert len(rows) == 1
    assert "wake_attempts_exhausted" in rows[0]["body"]
    assert RELAY_WORKERS_BUSY in rows[0]["body"]
    assert message_id in rows[0]["body"]
