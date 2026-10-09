"""Hook-owned durable observations forward native clocks without wire detours."""

from datetime import datetime, timedelta

import pytest

from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import control_plane_transport, db_helpers
from yoke_core.domain import session_activity_state as activity
from yoke_core.domain import session_message_types as clocks
from yoke_core.domain import session_native_process_observation as process
from yoke_core.domain import session_recovery_facts as recovery
from yoke_core.hooks import denial, stdin
from runtime.api.domain.coordination_claim_test_support import seed_session

MOMENT = parse_instant("2026-10-09T16:11:12.345678+05:45")
ZONES = ["UTC", "America/New_York", "Asia/Kathmandu"]
OPAQUE = "captured process start Fri Oct 9 10:26:12 2026"


def _open_call(conn):
    seed_session(conn, "hook-clock")
    assert activity.record_tool_call_started(
        conn,
        session_id="hook-clock",
        tool_use_id="clock-call",
        tool_name="Bash",
        started_at=MOMENT - timedelta(microseconds=1),
        command_summary=OPAQUE,
    )
    conn.commit()


def _local_owner(monkeypatch):
    # Only the locality boundary is supplied; writes use a real second PostgreSQL
    # connection and keep their normal commit/rollback/close behavior.
    monkeypatch.setattr(
        control_plane_transport,
        "local_connection_or_none",
        lambda _factory: db_helpers.connect(),
    )


@pytest.mark.parametrize("zone", ZONES)
def test_hook_denial_and_first_prompt_bind_native_clock_once_without_activity_bump(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _open_call(test_db)
    _local_owner(monkeypatch)
    monkeypatch.setattr(clocks, "utc_now", lambda: MOMENT)
    completed = []
    prompted = []
    original_finish = activity.record_tool_call_finished
    original_prompt = recovery.stamp_first_user_prompt

    def finish(conn, **kwargs):
        completed.append(kwargs["completed_at"])
        assert isinstance(kwargs["completed_at"], datetime)
        return original_finish(conn, **kwargs)

    def prompt(conn, session_id, at):
        prompted.append(at)
        assert isinstance(at, datetime)
        return original_prompt(conn, session_id, at)

    monkeypatch.setattr(activity, "record_tool_call_finished", finish)
    monkeypatch.setattr(recovery, "stamp_first_user_prompt", prompt)
    denial._close_denied_call(
        session_id="hook-clock",
        tool_use_id="clock-call",
        tool_name="Bash",
        outcome="denied",
    )
    stdin._stamp_first_user_prompt("hook-clock")
    assert completed == prompted == [MOMENT]
    row = test_db.execute(
        "SELECT started_at,completed_at,outcome,command_summary FROM session_tool_calls"
    ).fetchone()
    assert isinstance(row[1], datetime)
    assert tuple(row) == (MOMENT - timedelta(microseconds=1), MOMENT, "denied", OPAQUE)
    session = test_db.execute(
        "SELECT first_user_prompt_at,tool_call_count,last_tool_call_at FROM harness_sessions WHERE session_id='hook-clock'"
    ).fetchone()
    assert (
        isinstance(session[0], datetime)
        and session[0] == MOMENT
        and session[1] == 0
        and session[2] is None
    )
    monkeypatch.setattr(clocks, "utc_now", lambda: MOMENT + timedelta(microseconds=1))
    stdin._stamp_first_user_prompt("hook-clock")
    denial._close_denied_call(
        session_id="hook-clock",
        tool_use_id="clock-call",
        tool_name="Bash",
        outcome="denied",
    )
    assert (
        test_db.execute(
            "SELECT first_user_prompt_at FROM harness_sessions WHERE session_id='hook-clock'"
        ).fetchone()[0]
        == MOMENT
    )
    assert (
        test_db.execute("SELECT completed_at FROM session_tool_calls").fetchone()[0]
        == MOMENT
    )


@pytest.mark.parametrize("zone", ZONES)
def test_invalid_generated_hook_clocks_leave_durable_rows_unchanged(
    test_db, monkeypatch, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    _open_call(test_db)
    _local_owner(monkeypatch)
    monkeypatch.setattr(clocks, "utc_now", lambda: MOMENT.replace(tzinfo=None))
    denial._close_denied_call(
        session_id="hook-clock",
        tool_use_id="clock-call",
        tool_name="Bash",
        outcome="denied",
    )
    stdin._stamp_first_user_prompt("hook-clock")
    assert test_db.execute(
        "SELECT completed_at,outcome FROM session_tool_calls"
    ).fetchone()[:] == (None, None)
    assert (
        test_db.execute(
            "SELECT first_user_prompt_at FROM harness_sessions WHERE session_id='hook-clock'"
        ).fetchone()[0]
        is None
    )


@pytest.mark.parametrize("zone", ZONES)
def test_native_process_arrival_retains_microseconds_and_repeat_identity_clock(
    test_db, zone
):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    seed_session(test_db, "process-clock")
    evidence = {"pids": [12345], "process_start_times": {"12345": OPAQUE}}
    first = process.record_native_process_gone(
        test_db, "process-clock", evidence, observed_at=MOMENT
    )
    again = process.record_native_process_gone(
        test_db,
        "process-clock",
        evidence,
        observed_at=MOMENT + timedelta(microseconds=1),
    )
    row = test_db.execute(
        "SELECT native_process_gone_at FROM harness_sessions WHERE session_id='process-clock'"
    ).fetchone()
    assert isinstance(row[0], datetime) and row[0] == MOMENT
    assert first == again and first["observed_at"] == format_instant(MOMENT)
    assert first["evidence"]["process_start_times"] == {"12345": OPAQUE}


@pytest.mark.parametrize("value", ["", "2026-10-09", MOMENT.replace(tzinfo=None)])
def test_invalid_provided_process_arrival_refuses_before_observation_read(value):
    with pytest.raises(InvalidInstant):
        process.record_native_process_gone(
            object(), "process-clock", {}, observed_at=value
        )
