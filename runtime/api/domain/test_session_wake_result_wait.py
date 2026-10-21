"""Explicit wake waits follow durable claim and result state."""

from unittest.mock import Mock

import pytest

from yoke_core.domain import session_manual_wake


@pytest.mark.parametrize("attempt_kind", ["wake_relay", "wake_broker"])
@pytest.mark.parametrize(
    "claimed_at,completed_at,wait_seconds,expected_time,expected_code",
    [
        (None, None, 10, 1, "queued"),
        (1.25, None, 10, 1, "queued"),
        (0.75, 2, 10, 2, "delivered"),
        (1, 2, 10, 2, "delivered"),
        (0, 0, 10, 0, "delivered"),
        (0, None, 10, 10, "in_progress"),
        (None, None, 0.5, 0.5, "queued"),
        (0, None, 0.5, 0.5, "in_progress"),
        (None, None, 0, 0, "queued"),
    ],
)
def test_wake_wait_follows_claim_and_total_deadlines(
    monkeypatch, attempt_kind, claimed_at, completed_at, wait_seconds,
    expected_time, expected_code,
):
    elapsed = 0.0

    def sleep(seconds):
        nonlocal elapsed
        elapsed += seconds

    def details(_conn, _message_id):
        attempts = [{"attempt_kind": "hook_injection"}]
        if claimed_at is not None and elapsed >= claimed_at:
            complete = completed_at is not None and elapsed >= completed_at
            attempts.append({
                "attempt_kind": attempt_kind,
                "result_code": "delivered" if complete else None,
                "completed_at": "finished" if complete else None,
                "evidence": {"native": complete},
            })
        return {
            "attempts": attempts,
            "recipients": [{"wake_attempt_count": 1, "last_wake_at": "claimed"}],
        }

    monkeypatch.setattr(session_manual_wake, "monotonic", lambda: elapsed)
    monkeypatch.setattr(session_manual_wake, "sleep", sleep)
    monkeypatch.setattr(session_manual_wake, "message_details", details)
    receipt = {
        "message_id": "wake-message",
        "result_code": "queued",
        "recovery": "yoke messages get wake-message",
        "deduplicated": False,
    }

    result = session_manual_wake.wait_for_session_wake_result(
        Mock(), receipt, wait_seconds=wait_seconds,
    )

    assert elapsed == expected_time
    assert result["result_code"] == expected_code
    assert result["message_id"] == receipt["message_id"]
    assert result["deduplicated"] is False
    if expected_code == "queued":
        assert result == receipt
    else:
        assert result["attempt"]["attempt_kind"] == attempt_kind
        assert result["wake_attempt_count"] == 1
        assert result["last_wake_at"] == "claimed"
        assert result["evidence"] == {"native": expected_code == "delivered"}
    assert result["recovery"] == (
        None if expected_code == "delivered" else receipt["recovery"]
    )
