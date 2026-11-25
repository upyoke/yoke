"""A stale sweep preserves a session that is still taking message delivery."""

from datetime import timedelta

import pytest

from runtime.api.fixtures.session_reclaim_messages import (
    message_receipt,
    pending_message,
    start_message_attempt,
)
from runtime.api.sessions_test_support import _register
from runtime.api.sessions_test_support import conn as conn
from yoke_contracts.fleet_policy import WAKE_ACK_GRACE_SECONDS
from yoke_core.domain import sessions_analytics, sessions_claim_lifecycle_lock
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_store import acknowledge_recipient
from yoke_core.domain.session_message_types import utc_now
from yoke_core.domain.sessions_cleanup import clean_stale_harness_sessions
from yoke_core.domain.sessions_render_reclaim import find_stale_sessions

SESSION = "stale-wake-target"


@pytest.fixture
def wake_target(conn, monkeypatch):
    _register(conn, session_id=SESSION, executor="claude-cli")
    conn.execute(
        "UPDATE harness_sessions SET last_heartbeat=%s WHERE session_id=%s",
        (utc_now() - timedelta(days=2), SESSION),
    )
    message_id = pending_message(conn, SESSION)
    aborted = []

    def capture(name, *, session_id, context=None, **_kwargs):
        if name == "ReclaimAborted" and session_id == SESSION:
            aborted.append(context["abort_reason"])

    monkeypatch.setattr(sessions_analytics, "_emit_session_event", capture)
    return message_id, aborted


def _wake(conn, message_id, *, age_seconds, kind):
    at = utc_now() - timedelta(seconds=age_seconds)
    conn.execute(
        "UPDATE session_message_recipients SET last_wake_at=%s WHERE message_id=%s",
        (at, message_id),
    )
    start_message_attempt(conn, message_id, SESSION, kind=kind, started_at=at)
    conn.commit()


def _attempts(conn, message_id):
    return {
        row["attempt_kind"]: (row["completed_at"], row["result_code"])
        for row in conn.execute(
            "SELECT attempt_kind, completed_at, result_code "
            "FROM session_message_attempts WHERE message_id=%s",
            (message_id,),
        ).fetchall()
    }


@pytest.mark.parametrize(
    "age,kind",
    [
        (1, "wake_relay"),
        (WAKE_ACK_GRACE_SECONDS + 60, "wake_relay"),
        (WAKE_ACK_GRACE_SECONDS + 60, "wake_broker"),
    ],
)
def test_sweep_preserves_wake_during_grace_or_open_attempt(
    conn, wake_target, age, kind
):
    message_id, aborted = wake_target
    _wake(conn, message_id, age_seconds=age, kind=kind)

    assert SESSION not in {row["session_id"] for row in find_stale_sessions(conn)}
    assert clean_stale_harness_sessions(conn, project_ids=[1])["total_reclaimed"] == 0
    assert aborted == ["wake_delivery_in_flight"]
    assert message_receipt(conn, message_id)["state"] == "pending"
    assert _attempts(conn, message_id)[kind] == (None, None)
    assert (
        conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id=%s", (SESSION,)
        ).fetchone()["ended_at"]
        is None
    )


@pytest.mark.parametrize(
    "age,reclaimed", [(1, False), (WAKE_ACK_GRACE_SECONDS + 60, True)]
)
def test_completed_attempt_leaves_only_acknowledgement_window(
    conn, wake_target, age, reclaimed
):
    message_id, aborted = wake_target
    _wake(conn, message_id, age_seconds=age, kind="wake_relay")
    conn.execute(
        "UPDATE session_message_attempts SET completed_at=%s,result_code='wake_delivered' "
        "WHERE message_id=%s",
        (utc_now(), message_id),
    )
    conn.commit()

    assert (
        clean_stale_harness_sessions(conn, project_ids=[1])["total_reclaimed"]
        == reclaimed
    )
    if reclaimed:
        assert aborted == []
        assert message_receipt(conn, message_id)["state"] == "cancelled"
        return

    assert aborted == ["wake_delivery_in_flight"]
    lease = lease_for_hook(conn, session_id=SESSION, hook_event="PreToolUse", limit=1)
    assert lease["messages"][0]["message_id"] == message_id
    assert (
        complete_hook_lease(
            conn, lease_id=lease["lease_id"], injected=True, result="injected"
        )
        == 1
    )
    acknowledge_recipient(
        conn, message_id=message_id, session_id=SESSION, acknowledged_at=utc_now()
    )
    conn.commit()

    receipt = message_receipt(conn, message_id)
    assert receipt["state"] == "acknowledged"
    assert receipt["acknowledged_at"] is not None
    assert {result for _, result in _attempts(conn, message_id).values()} == {
        "wake_delivered",
        "injected",
    }


def test_locked_recheck_sees_wake_started_after_snapshot(
    conn, wake_target, monkeypatch
):
    message_id, aborted = wake_target
    lock = sessions_claim_lifecycle_lock.lock_session_rows_for_claim_lifecycle

    def start_wake_before_lock(conn, session_ids):
        _wake(conn, message_id, age_seconds=1, kind="wake_relay")
        return lock(conn, session_ids)

    monkeypatch.setattr(
        sessions_claim_lifecycle_lock,
        "lock_session_rows_for_claim_lifecycle",
        start_wake_before_lock,
    )

    result = clean_stale_harness_sessions(conn, project_ids=[1])
    assert result["total_reclaimed"] == 0
    assert result["skipped_between_turns"][0]["recheck"] is True
    assert aborted == ["wake_delivery_in_flight"]
    assert message_receipt(conn, message_id)["state"] == "pending"
    assert _attempts(conn, message_id)["wake_relay"] == (None, None)
