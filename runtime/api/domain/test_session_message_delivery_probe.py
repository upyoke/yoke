"""The record a declining delivery leaves against its pending receipt."""

from __future__ import annotations

import json

import pytest

import yoke_core.domain.session_message_delivery as message_delivery
from yoke_core.domain.session_message_delivery import (
    complete_hook_lease,
    lease_for_hook,
)
from yoke_core.domain.session_message_delivery_probe import (
    DELIVERY_PROBE_ADAPTER_REVISION,
    PROBE_LEASE_FAILED,
    PROBE_NO_LEASABLE_RECEIPT,
    PROBE_SESSION_NOT_DELIVERABLE,
    bounded_detail,
    record_undelivered_receipts,
)
from yoke_core.domain.session_message_attempt_reads import message_attempt_evidence
from yoke_core.domain.session_message_service import send_message
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from runtime.api.domain.test_session_message_support import (
    NOW,
    message_connection,
    selector,
)


@pytest.fixture(autouse=True)
def _fixed_message_clock(monkeypatch):
    monkeypatch.setattr(message_delivery, "utc_now", lambda: NOW)


def _send(conn, *, body="Persistent instructions.") -> str:
    return send_message(
        conn,
        actor_id=10,
        sender_session_id="s1",
        selector=selector(session_ids=["s1"]),
        body=body,
        now=NOW,
    )["message_id"]


def _probe_rows(conn) -> list[dict[str, str]]:
    rows = conn.execute(
        "SELECT attempt_id,message_id,target_session_id,attempt_kind,"
        "adapter_revision,lease_id,started_at,completed_at,result_code,evidence "
        "FROM session_message_attempts WHERE adapter_revision=? "
        "ORDER BY attempt_id",
        (DELIVERY_PROBE_ADAPTER_REVISION,),
    ).fetchall()
    return [dict(row) for row in rows]


def test_declining_delivery_records_its_reason_against_the_pending_receipt() -> None:
    conn = message_connection()
    message_id = _send(conn)

    recorded = record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="SessionStart",
        reason=PROBE_SESSION_NOT_DELIVERABLE,
        now=NOW,
    )

    assert recorded == 1
    row = _probe_rows(conn)[0]
    assert row["message_id"] == message_id
    assert row["target_session_id"] == "s1"
    assert row["attempt_kind"] == "hook"
    assert row["lease_id"] is None
    assert row["started_at"] == row["completed_at"]
    assert row["result_code"] == PROBE_SESSION_NOT_DELIVERABLE
    assert json.loads(row["evidence"]) == {
        "hook_event": "SessionStart",
        "probe_detail": "",
    }


def test_repeated_declines_fold_into_one_row_per_event_and_reason() -> None:
    conn = message_connection()
    _send(conn)

    for _ in range(3):
        record_undelivered_receipts(
            conn,
            session_id="s1",
            hook_event="SessionStart",
            reason=PROBE_SESSION_NOT_DELIVERABLE,
            now=NOW,
        )
    record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="SessionStart",
        reason=PROBE_LEASE_FAILED,
        detail="OperationalError",
        now=NOW,
    )
    record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="PostToolUse",
        reason=PROBE_SESSION_NOT_DELIVERABLE,
        now=NOW,
    )

    rows = _probe_rows(conn)
    assert len(rows) == 3
    assert {
        (json.loads(row["evidence"])["hook_event"], row["result_code"]) for row in rows
    } == {
        ("SessionStart", PROBE_SESSION_NOT_DELIVERABLE),
        ("SessionStart", PROBE_LEASE_FAILED),
        ("PostToolUse", PROBE_SESSION_NOT_DELIVERABLE),
    }


def test_a_receipt_that_already_reached_the_session_records_nothing() -> None:
    conn = message_connection()
    _send(conn)
    lease = lease_for_hook(conn, session_id="s1", hook_event="PreToolUse", limit=10)
    complete_hook_lease(
        conn, lease_id=lease["lease_id"], injected=True, result="injected"
    )

    recorded = record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="SessionStart",
        reason=PROBE_NO_LEASABLE_RECEIPT,
        now=NOW,
    )

    assert recorded == 0
    assert _probe_rows(conn) == []


def test_an_empty_inbox_records_nothing() -> None:
    conn = message_connection()

    assert (
        record_undelivered_receipts(
            conn,
            session_id="s1",
            hook_event="SessionStart",
            reason=PROBE_SESSION_NOT_DELIVERABLE,
            now=NOW,
        )
        == 0
    )
    assert _probe_rows(conn) == []


def test_probe_rows_leave_wake_and_lease_settlement_untouched() -> None:
    conn = message_connection()
    _send(conn)
    record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="SessionStart",
        reason=PROBE_SESSION_NOT_DELIVERABLE,
        now=NOW,
    )

    lease = lease_for_hook(conn, session_id="s1", hook_event="SessionStart", limit=10)
    assert lease and lease["messages"]
    assert (
        complete_hook_lease(
            conn, lease_id=lease["lease_id"], injected=True, result="injected"
        )
        == 1
    )
    assert [row["session_id"] for row in wake_eligible_recipients(conn, now=NOW)] == []


def test_the_message_view_shows_the_declining_event_and_its_reason() -> None:
    conn = message_connection()
    message_id = _send(conn)
    record_undelivered_receipts(
        conn,
        session_id="s1",
        hook_event="SessionStart",
        reason=PROBE_LEASE_FAILED,
        detail="OperationalError",
        now=NOW,
    )

    attempt = message_attempt_evidence(conn, message_id)["attempts"][0]

    assert attempt["adapter_revision"] == DELIVERY_PROBE_ADAPTER_REVISION
    assert attempt["result_code"] == PROBE_LEASE_FAILED
    assert attempt["evidence"] == {
        "hook_event": "SessionStart",
        "probe_detail": "OperationalError",
    }


def test_an_unknown_reason_is_refused_rather_than_recorded() -> None:
    conn = message_connection()
    _send(conn)

    with pytest.raises(ValueError, match="unknown delivery probe reason"):
        record_undelivered_receipts(
            conn,
            session_id="s1",
            hook_event="SessionStart",
            reason="probe_made_up",
            now=NOW,
        )
    assert _probe_rows(conn) == []


def test_detail_carries_a_classification_and_never_free_text() -> None:
    assert bounded_detail("OperationalError") == "OperationalError"
    assert bounded_detail('relation "x" does not exist; DROP TABLE') == (
        "relationxdoesnotexistDROPTABLE"
    )
    assert bounded_detail(None) == ""
    assert len(bounded_detail("E" * 200)) == 64
