"""Orthogonal session facts across harnesses and pause/process combinations."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.session_queue_posture import (
    session_pause_declared,
    session_pause_mode_sql,
)
from yoke_core.domain.session_native_process_observation import (
    current_native_process_observation,
)
from yoke_core.domain.session_state import session_state

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)


def row(**extra):
    return {
        "session_id": "session",
        "executor": "codex",
        "mode": "wait",
        "turn_posture": "running",
        "last_tool_call_at": NOW - timedelta(minutes=1),
        "last_heartbeat": NOW,
        "holds_work_claim": False,
        **extra,
    }


@pytest.mark.parametrize("executor", ["codex", "claude-code", "cursor"])
@pytest.mark.parametrize("mode", ["wait", "parked"])
@pytest.mark.parametrize("posture", ["running", "waiting", None])
@pytest.mark.parametrize("claim", [False, True])
@pytest.mark.parametrize("gone", [False, True])
def test_presence_activity_intent_are_independent(executor, mode, posture, claim, gone):
    facts = row(
        executor=executor,
        mode=mode,
        turn_posture=posture,
        holds_work_claim=claim,
        native_process_gone_at=NOW if gone else None,
    )
    state = session_state(facts, now=NOW)
    assert state["presence"] == ("gone" if gone else "present")
    assert state["intent"]["state"] == ("parked" if mode == "parked" else "none")
    expected = (
        "silent"
        if gone
        else "working"
        if mode == "wait" and posture == "running"
        else "between_turns"
    )
    assert state["activity"] == expected
    assert state["custody"]["holds_work_claim"] == claim
    if claim:
        assert state["custody"]["reclaimable"] is False
    assert session_pause_declared(facts) == (mode == "parked")


@pytest.mark.parametrize("end", ["ended_at", "terminated_at"])
def test_end_stamps_win_over_recent_activity_and_process(end):
    assert session_state(row(**{end: NOW}), now=NOW)["presence"] == "ended"


def test_heartbeat_and_episode_cannot_hide_death_but_later_tool_can():
    facts = row(
        native_process_gone_at=NOW - timedelta(seconds=1), episode_started_at=NOW
    )
    assert session_state(facts, now=NOW)["presence"] == "gone"
    assert current_native_process_observation(facts, include_expected_exit=True)
    facts["last_tool_call_at"] = NOW
    assert session_state(facts, now=NOW)["presence"] == "present"
    assert current_native_process_observation(facts, include_expected_exit=True) is None


def test_tool_idle_threshold_is_project_owned_and_ignores_heartbeat():
    facts = row(last_tool_call_at=NOW - timedelta(minutes=10))
    assert session_state(facts, now=NOW)["activity"] == "working"
    assert (
        session_state({**facts, "session_idle_minutes": 5}, now=NOW)["activity"]
        == "silent"
    )
    assert session_state(row(last_tool_call_at=None), now=NOW)["activity"] == "silent"


@pytest.mark.parametrize("age,live", [(44, True), (45, False), (46, False)])
def test_open_calls_share_a_bounded_definition(age, live):
    start = NOW - timedelta(minutes=age)
    state = session_state(
        row(last_tool_call_at=start, open_tool_call_at=start), now=NOW
    )
    assert state["in_flight"] is live
    assert state["activity"] == ("working" if live else "silent")


def test_pause_retains_its_reason_and_custody_without_claiming_work():
    state = session_state(
        row(mode="parked", quiet_reason="waiting for review", holds=[{"kind": "item"}]),
        now=NOW,
    )
    assert state["intent"] == {
        "state": "parked",
        "reason": "waiting for review",
        "awaiting_who": None,
    }
    assert state["custody"]["holds"] == [{"kind": "item"}]
    assert state["next_actor"]["actor"] == "parent_or_steering"


def test_board_pause_sql_does_not_infer_intent_from_posture():
    assert "turn_posture" not in session_pause_mode_sql("session")


def test_responsive_hooks_do_not_prove_tool_progress_or_hide_process_death():
    from yoke_core.domain.session_staleness import activity_liveness

    facts = row(last_tool_call_at=NOW - timedelta(hours=1))
    assert session_state(facts, now=NOW)["activity"] == "silent"
    assert activity_liveness(facts, now=NOW) == "active"
    facts["native_process_gone_at"] = NOW - timedelta(minutes=30)
    assert activity_liveness(facts, now=NOW) == "stale"


def test_roster_uses_the_projects_configured_tool_idle_threshold(test_db):
    from runtime.api.domain.handlers.sessions_list_handler_test_support import (
        _insert_session,
    )
    from yoke_contracts.timestamps import utc_now
    from yoke_core.domain.sessions_list_read import list_sessions
    from yoke_core.domain.project_policy_capabilities import set_project_policy_value

    now = utc_now()
    _insert_session(test_db, "configured-idle", last_heartbeat=now)
    test_db.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s, turn_posture='running' WHERE session_id=%s",
        (now - timedelta(minutes=10), "configured-idle"),
    )
    for minutes, expected in ((5, "silent"), (15, "working")):
        set_project_policy_value(test_db, 1, "session_idle_minutes", minutes)
        test_db.commit()
        result = list_sessions(session_id="configured-idle")[0]
        assert result["session_state"]["activity"] == expected


@pytest.mark.parametrize("posture", ["running", "waiting"])
def test_a_roster_turn_marker_is_activity_rather_than_awaiting_intent(posture):
    facts = row(turn_posture=posture, declared_wait={"kind": "turn_posture"})
    assert session_state(facts, now=NOW)["intent"]["state"] == "none"
    assert session_pause_declared(facts) is False


def test_an_explicit_wait_carries_its_reason_and_addressee():
    facts = row(
        declared_wait={
            "kind": "dependency",
            "reason": "awaiting dependency",
            "awaiting_who": "another_item",
        }
    )
    state = session_state(facts, now=NOW)
    assert state["intent"] == {
        "state": "awaiting",
        "reason": "awaiting dependency",
        "awaiting_who": "another_item",
    }
    assert state["activity"] != "working"
    assert session_pause_declared(facts) is True
