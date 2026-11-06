"""Every reclaim adapter agrees on terminal custody and current open calls."""

from datetime import datetime, timedelta, timezone

import pytest

from yoke_core.domain.session_automatic_reclaim import automatic_reclaim
from yoke_core.domain.session_reclaim_activity import (
    classify_activity,
    classify_reclaimable,
    read_activity_signals,
)
from yoke_core.domain.session_reclaim_activity_bulk import latest_activity_by_session
from yoke_core.domain.session_state import session_in_flight, session_state
from runtime.api.domain.handlers.sessions_list_handler_test_support import _insert_session

NOW = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=3)


@pytest.mark.parametrize("end", ["ended_at", "terminated_at"])
@pytest.mark.parametrize("held", [True, False])
def test_terminal_custody_is_reclaimable_even_when_parked(end, held):
    facts = {
        "session_id": "holder", "holds_work_claim": held, "mode": "parked",
        "last_heartbeat": NOW, "last_tool_call_at": NOW, end: NOW,
        "open_tool_call_at": NOW, "turn_posture": "running",
    }
    result = automatic_reclaim(facts, now=NOW)
    assert (result.is_reclaimable, result.reason) == (True, "ended")
    assert not session_in_flight(facts, now=NOW)
    assert session_state(facts, now=NOW)["custody"]["reclaimable"] is True


@pytest.mark.parametrize("extra,live", [
    ({}, True),
    ({"turn_posture": "waiting"}, False),
    ({"mode": "parked", "turn_posture_at": NOW}, False),
    ({"native_process_gone_at": NOW}, False),
    ({"ended_at": NOW}, False),
    ({"terminated_at": NOW}, False),
    ({"last_tool_call_at": NOW}, False),
    ({"open_tool_call_at": OLD}, False),
])
def test_reclaim_and_session_model_use_the_same_in_flight_rule(extra, live):
    start = NOW - timedelta(minutes=25)
    facts = {
        "session_id": "worker", "last_heartbeat": OLD,
        "last_tool_call_at": start, "open_tool_call_at": start,
        "turn_posture": "running", "holds_work_claim": False, **extra,
    }
    result = automatic_reclaim(facts, now=NOW)
    assert session_in_flight(facts, now=NOW) is live
    assert result.evidence.is_in_flight(now=NOW) is live
    assert result.is_reclaimable == (not live and facts["last_tool_call_at"] != NOW)
    held = automatic_reclaim({**facts, "holds_work_claim": True}, now=NOW)
    assert held.is_reclaimable == bool(facts.get("ended_at") or facts.get("terminated_at"))


@pytest.mark.parametrize("end", ["ended_at", "terminated_at"])
def test_single_and_cleanup_reads_agree_on_terminal_sessions(test_db, end):
    _insert_session(test_db, "terminal-holder", last_heartbeat=NOW, **{end: NOW})
    decisions = [classify_reclaimable(test_db, "terminal-holder", scope=scope)
                 for scope in ("item_claim", "session_cleanup")]
    evidence = read_activity_signals(test_db, "terminal-holder")
    decisions.append(classify_activity(evidence, holds_work_claim=True, now=NOW))
    assert {(result.is_reclaimable, result.reason) for result in decisions} == {(True, "ended")}
    assert not evidence.in_flight
    assert latest_activity_by_session(test_db, ["terminal-holder"])["terminal-holder"] == evidence.activity_at
