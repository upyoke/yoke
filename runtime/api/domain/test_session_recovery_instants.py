"""Exact activity/recovery clocks, durable budgets and strict endpoint ingress."""

import json
from datetime import timedelta
from uuid import uuid4

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from runtime.api.domain.session_vendor_error_test_support import (
    worker_connection,
    SESSION_ID,
)
from yoke_contracts.timestamps import InvalidInstant, format_instant, parse_instant
from yoke_core.domain import session_recovery_facts as facts
from yoke_core.domain import session_activity_state as activity
from yoke_core.domain import observe_timing as timing
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.turn_end_promised_work_gate import (
    _at_reinjection_cap,
    REINJECTION_COOLDOWN,
)

MOMENT = parse_instant("1969-12-31T23:59:59.123456Z")
OFFSET = "1970-01-01T05:29:59.123456+05:30"


@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Kolkata"])
def test_activity_replay_and_recovery_keep_microseconds(test_db, zone):
    test_db.execute("SELECT set_config('TimeZone',%s,false)", (zone,))
    sid = str(uuid4())
    insert_session(test_db, sid)
    facts.stamp_first_user_prompt(test_db, sid, OFFSET)
    facts.stamp_first_user_prompt(test_db, sid, MOMENT + timedelta(seconds=1))
    later = MOMENT + timedelta(microseconds=1)
    assert activity.record_tool_call_finished(
        test_db,
        session_id=sid,
        tool_use_id="completed-first",
        tool_name="Read",
        event_name="HarnessToolCallCompleted",
        outcome="completed",
        completed_at=later,
    )
    assert activity.record_tool_call_started(
        test_db,
        session_id=sid,
        tool_use_id="completed-first",
        tool_name="Read",
        started_at=OFFSET,
    )
    assert not activity.record_tool_call_finished(
        test_db,
        session_id=sid,
        tool_use_id="completed-first",
        tool_name="Read",
        event_name="HarnessToolCallCompleted",
        outcome="completed",
        completed_at=later,
    )
    facts.stamp_completed_work(test_db, sid, MOMENT)
    assert test_db.execute(
        "SELECT started_at,completed_at FROM session_tool_calls WHERE session_id=%s",
        (sid,),
    ).fetchone() == (MOMENT, later)
    assert test_db.execute(
        "SELECT first_user_prompt_at,first_completed_work_at,last_completed_work_at,last_tool_call_at,tool_call_count "
        "FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone() == (MOMENT, later, later, later, 1)
    key = facts.resume_episode_key(later)
    assert key == format_instant(later)
    assert facts.reserve_resume_attempt(test_db, sid, episode_key=key, budget=1) == 1
    observed = later + timedelta(microseconds=1)
    facts.record_native_turn_end(
        test_db,
        sid,
        observation={
            "observed_at": format_instant(observed),
            "error_message": "temporary capacity",
            "codex_error_info": "other",
            "opaque": OFFSET,
        },
        recorded_at=observed,
    )
    row = dict(
        test_db.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (sid,)
        ).fetchone()
    )
    assert facts.native_turn_end(row)["recorded_at"] == observed
    assert json.loads(row["native_turn_end_observation"])["opaque"] == OFFSET
    assert (
        facts.resume_attempts_spent(
            row, episode_key=facts.resume_episode_key(row["last_tool_call_at"])
        )
        == 1
    )
    assert facts.reserve_resume_attempt(test_db, sid, episode_key=key, budget=1) is None
    states = vendor_error_states(test_db, authorized_projects=(1,), now=observed)
    state = next(state for state in states if state["session_id"] == sid)
    assert state["attempts"] == 1
    assert state["episode_key"] == key
    assert state["observed_at"] == format_instant(observed)
    facts.record_promised_work_hold(test_db, session_id=sid, item_id=1, at=OFFSET)
    assert facts.promised_work_holds(test_db, session_id=sid, item_id=1) == (MOMENT, 1)
    assert _at_reinjection_cap(
        test_db, sid, 1, now=MOMENT + REINJECTION_COOLDOWN - timedelta(microseconds=1)
    )
    assert not _at_reinjection_cap(test_db, sid, 1, now=MOMENT + REINJECTION_COOLDOWN)


def test_sqlite_recovery_projects_owned_observation_and_keeps_budget():
    conn = worker_connection()
    try:
        facts.stamp_first_user_prompt(conn, SESSION_ID, OFFSET)
        facts.stamp_completed_work(conn, SESSION_ID, OFFSET)
        facts.record_native_turn_end(
            conn,
            SESSION_ID,
            observation={"observed_at": OFFSET, "opaque": OFFSET},
            recorded_at=OFFSET,
        )
        row = dict(
            conn.execute(
                "SELECT * FROM harness_sessions WHERE session_id=?", (SESSION_ID,)
            ).fetchone()
        )
        assert row["first_user_prompt_at"] == format_instant(MOMENT)
        assert row["last_completed_work_at"] == format_instant(MOMENT)
        assert row["native_turn_end_recorded_at"] == format_instant(MOMENT)
        assert facts.native_turn_end(row)["recorded_at"] == MOMENT
        observation = json.loads(row["native_turn_end_observation"])
        assert observation == {"observed_at": format_instant(MOMENT), "opaque": OFFSET}
        assert facts.resume_episode_key(None) == ""
        assert (
            facts.reserve_resume_attempt(conn, SESSION_ID, episode_key="", budget=1)
            == 1
        )
        assert (
            facts.reserve_resume_attempt(conn, SESSION_ID, episode_key="", budget=1)
            is None
        )
        for bad in (
            "",
            "1969-12-31T23:59:59",
            "1969-12-31",
            MOMENT.replace(tzinfo=None),
        ):
            with pytest.raises(InvalidInstant):
                facts.stamp_completed_work(conn, SESSION_ID, bad)
        assert conn.execute(
            "SELECT last_completed_work_at FROM harness_sessions WHERE session_id=?",
            (SESSION_ID,),
        ).fetchone()[0] == format_instant(MOMENT)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "bad", ["", "1969-12-31T23:59:59", "1969-12-31", MOMENT.replace(tzinfo=None)]
)
def test_invalid_activity_ingress_refuses_before_any_state_changes(test_db, bad):
    sid = str(uuid4())
    insert_session(test_db, sid)
    with pytest.raises(InvalidInstant) as refusal:
        activity.apply_envelope_state(
            test_db,
            {
                "event_name": "HarnessToolCallCompleted",
                "session_id": sid,
                "event_time": bad,
                "tool_use_id": "invalid-call",
            },
        )
    assert refusal.value.code == "invalid_instant"
    assert test_db.execute(
        "SELECT tool_call_count,last_tool_call_at,turn_posture_at FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone() == (0, None, None)
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM session_tool_calls WHERE session_id=%s", (sid,)
        ).fetchone()[0]
        == 0
    )


def test_captured_elapsed_uses_integer_rounding_and_exact_failure_boundaries():
    for microseconds, milliseconds in (
        (499, 0),
        (500, 0),
        (501, 1),
        (1499, 1),
        (1500, 2),
        (2500, 2),
    ):
        assert (
            timing.measure_elapsed(
                MOMENT, MOMENT + timedelta(microseconds=microseconds)
            ).milliseconds
            == milliseconds
        )
    assert (
        timing.measure_elapsed(MOMENT, MOMENT - timedelta(microseconds=1)).status
        == timing.TIMING_INVALID_NEGATIVE_ELAPSED
    )
    assert (
        timing.measure_elapsed(
            MOMENT, MOMENT + timedelta(milliseconds=timing.MAX_PLAUSIBLE_ELAPSED_MS)
        ).status
        == timing.TIMING_MEASURED
    )
    assert (
        timing.measure_elapsed(
            MOMENT,
            MOMENT
            + timedelta(milliseconds=timing.MAX_PLAUSIBLE_ELAPSED_MS, microseconds=1),
        ).status
        == timing.TIMING_INVALID_IMPLAUSIBLE_ELAPSED
    )
    assert (
        timing.measure_elapsed("1969-12-31T23:59:59", MOMENT).status
        == timing.TIMING_INVALID_ENDPOINT_FORMAT
    )
    with pytest.raises(InvalidInstant):
        timing.arriving_start_supersedes("unreadable", MOMENT)
    with pytest.raises(InvalidInstant):
        timing.delivery_is_pending(MOMENT, now=MOMENT.replace(tzinfo=None))


def test_process_evidence_normalizes_exit_clock_and_preserves_process_identity(test_db):
    from yoke_core.domain.session_native_process_observation import (
        record_native_process_gone,
    )

    sid = str(uuid4())
    insert_session(test_db, sid)
    evidence = {
        "pids": [123],
        "process_start_times": {"123": OFFSET},
        "native_exit_at": OFFSET,
    }
    result = record_native_process_gone(
        test_db, sid, evidence, observed_at=MOMENT + timedelta(seconds=1)
    )
    assert result["observed_at"] == format_instant(MOMENT)
    assert result["evidence"]["native_exit_at"] == format_instant(MOMENT)
    assert result["evidence"]["process_start_times"] == evidence["process_start_times"]
    row = test_db.execute(
        "SELECT native_process_gone_at,native_process_gone_evidence FROM harness_sessions WHERE session_id=%s",
        (sid,),
    ).fetchone()
    assert row[0] == MOMENT
    assert json.loads(row[1]) == result["evidence"]
