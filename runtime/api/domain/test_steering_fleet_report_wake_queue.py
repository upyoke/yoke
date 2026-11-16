"""Queued wakes are waiting only while their machine demonstrates progress."""

from dataclasses import replace
from datetime import timedelta

import pytest

from runtime.api.steering_fleet_test_helpers import (
    ANSWERER,
    ASKER,
    BEFORE_THAT,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    compose,
    seed_delivery_attempt,
    seed_message,
    seed_relay,
    seed_session,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.steering_fleet_report_delivery_states import (
    NEVER_ATTEMPTED,
    WAKE_DRAINING,
)
from yoke_core.domain.steering_fleet_report_render_undelivered import undelivered_line
from yoke_core.domain.steering_fleet_report_undelivered import undelivered_messages
from yoke_core.domain.steering_fleet_report_wake_queue import draining_wake_positions
from yoke_core.domain.session_relay_policy import relay_policy


@pytest.fixture
def fleet(test_db):
    seed_session(test_db, ASKER, last_tool_call_at=BEFORE_THAT)
    seed_session(test_db, ANSWERER, last_tool_call_at=BEFORE_THAT)
    seed_relay(test_db)
    # Seed deliberately out of claim order on one machine.
    for message, recipient in (
        ("msg-c", ANSWERER),
        ("msg-b", ASKER),
        ("msg-a", ANSWERER),
        ("progress", ASKER),
    ):
        seed_message(test_db, message, sender=ASKER, to=recipient, at=LONG_AGO)
    test_db.execute("UPDATE session_message_recipients SET machine_id='machine-1'")
    test_db.execute(
        "UPDATE session_message_recipients SET state='acknowledged' "
        "WHERE message_id='progress'"
    )
    seed_delivery_attempt(
        test_db,
        "recent",
        message_id="progress",
        to=ASKER,
        result_code="accepted",
        started_at=NOW,
    )
    test_db.commit()
    return test_db


def _rows(conn, now=NOW):
    return undelivered_messages(conn, project_id=PROJECT_ID, now=now)


def _positions(conn):
    # A report reader must not enqueue wakes, expire rows or change receipts.
    class ReadOnly:
        def __getattr__(self, name):
            return getattr(conn, name)

        def execute(self, sql, params=()):
            assert sql.lstrip().startswith("SELECT")
            return conn.execute(sql, params)

    return draining_wake_positions(
        ReadOnly(), machine_ids=["machine-1"], now=parse_instant(NOW)
    )


def test_queue_reports_positions_in_claim_order_without_a_false_alarm(fleet):
    rows = _rows(fleet)
    assert {row.delivery_state for row in rows} == {WAKE_DRAINING}
    by_session = {row.session_id: row for row in rows}
    assert by_session[ANSWERER].wake_queue_positions == (("msg-a", 1), ("msg-c", 3))
    assert by_session[ASKER].wake_queue_positions == (("msg-b", 2),)
    for row in rows:
        assert row.in_delivery and not row.needs_seat_action
        line = undelivered_line(row)
        assert "queued in machine wake queue" in line
        assert "no delivery attempted" not in line
        assert "session wake" not in line
    assert "positions msg-a: 1, msg-c: 3" in undelivered_line(by_session[ANSWERER])
    assert _positions(fleet) == {
        ("msg-a", ANSWERER): 1,
        ("msg-b", ASKER): 2,
        ("msg-c", ANSWERER): 3,
    }


@pytest.mark.parametrize(
    "condition",
    ["disconnected", "inactive", "stale", "hook_only", "other_machine", "no_progress"],
)
def test_skipped_or_unserved_receipts_remain_never_attempted(fleet, condition):
    if condition == "disconnected":
        fleet.execute("UPDATE session_relays SET connected_until=%s", (LONG_AGO,))
    elif condition == "inactive":
        fleet.execute("UPDATE session_relays SET state='offline'")
    elif condition == "stale":
        fleet.execute("UPDATE session_message_attempts SET started_at=%s", (LONG_AGO,))
    elif condition == "hook_only":
        fleet.execute("UPDATE session_message_attempts SET attempt_kind='hook'")
    elif condition == "other_machine":
        fleet.execute(
            "UPDATE session_message_recipients SET machine_id='other' "
            "WHERE message_id='progress'"
        )
    else:
        fleet.execute("DELETE FROM session_message_attempts")
    rows = _rows(fleet)
    assert {row.delivery_state for row in rows} == {NEVER_ATTEMPTED}
    assert all(row.needs_seat_action for row in rows)
    assert all("no delivery attempted" in undelivered_line(row) for row in rows)


def test_progress_expires_after_three_polls_even_with_a_connected_relay(fleet):
    later = parse_instant(NOW) + timedelta(seconds=3 * relay_policy().poll_seconds + 1)
    assert {row.delivery_state for row in _rows(fleet, later)} == {NEVER_ATTEMPTED}


@pytest.mark.parametrize(
    "exclusion", ["future", "expired", "cancelled", "lease", "attempt"]
)
def test_queue_excludes_receipts_the_wake_claim_cannot_take(fleet, exclusion):
    if exclusion == "future":
        fleet.execute(
            "UPDATE session_message_recipients SET wake_after=%s "
            "WHERE message_id='msg-a'",
            ("2026-08-26T13:00:00Z",),
        )
    elif exclusion == "expired":
        fleet.execute(
            "UPDATE session_messages SET expires_at=%s WHERE message_id='msg-a'",
            (LONG_AGO,),
        )
    elif exclusion == "cancelled":
        fleet.execute(
            "UPDATE session_messages SET cancelled_at=%s WHERE message_id='msg-a'",
            (NOW,),
        )
    elif exclusion == "lease":
        fleet.execute(
            "UPDATE session_message_recipients SET injection_lease_id='held', "
            "injection_lease_expires_at=%s WHERE message_id='msg-a'",
            ("2026-08-26T13:00:00Z",),
        )
    else:
        seed_delivery_attempt(
            fleet,
            "open",
            message_id="msg-a",
            to=ANSWERER,
            result_code="accepted",
            started_at=NOW,
        )
        fleet.execute(
            "UPDATE session_message_attempts SET completed_at=NULL "
            "WHERE attempt_id='open'"
        )
    assert _positions(fleet) == {("msg-b", ASKER): 1, ("msg-c", ANSWERER): 2}


def test_expired_injection_lease_reenters_the_queue(fleet):
    fleet.execute(
        "UPDATE session_message_recipients SET injection_lease_id='expired', "
        "injection_lease_expires_at=%s WHERE message_id='msg-a'",
        (LONG_AGO,),
    )
    assert _positions(fleet)[("msg-a", ANSWERER)] == 1


def test_queue_positions_do_not_enter_report_identity(fleet):
    report = compose(fleet)
    assert report.undelivered
    moved = replace(
        report,
        undelivered=tuple(
            replace(row, wake_queue_positions=(("msg-a", 99),))
            for row in report.undelivered
        ),
    )
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_read import _age_blind

    assert report_dict(report)["undelivered"][0]["wake_queue_positions"]
    assert _age_blind(report_dict(moved)) == _age_blind(report_dict(report))
    assert moved.fingerprint() == report.fingerprint()
    assert (
        replace(report, undelivered=()).fingerprint() == report.fingerprint()
    )


def test_positions_name_each_receipt_when_wake_and_send_order_differ(fleet):
    fleet.execute(
        "UPDATE session_message_recipients SET wake_after=%s WHERE message_id='msg-c'",
        (BEFORE_THAT,),
    )
    row = next(entry for entry in _rows(fleet) if entry.session_id == ANSWERER)
    assert row.wake_queue_positions == (("msg-c", 1), ("msg-a", 2))
    assert "positions msg-c: 1, msg-a: 2" in undelivered_line(row)
