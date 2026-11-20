"""A holder whose subagent is working is not an idle holder (YOK-5554).

Production QA found the gap: the QA host idle clock counted a subagent's
calls, but the fleet report's holder read and the sessions roster selected
only the parent's ``last_tool_call_at``, so a parent waiting on a working
subagent still showed under idle holders.
"""

from __future__ import annotations

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_session,
    _iso,
)
from runtime.api.domain.steering_fleet_report_holder_read_test_support import _claim
from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
    seed_steering_scope,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain.steering_fleet_report_holders import (
    claim_holders,
    quiet_holders,
    with_session_state,
)


def _holders(fleet, session_id, child_at):
    seed_session(fleet, session_id, last_tool_call_at=LONG_AGO)
    _claim(fleet, session_id, 1)
    fleet.execute(
        "UPDATE harness_sessions SET last_child_tool_call_at=%s WHERE session_id=%s",
        (child_at, session_id),
    )
    fleet.commit()
    return with_session_state(
        claim_holders(fleet, project_id=PROJECT_ID, now=NOW),
        now=NOW,
        idle_after_seconds=20 * 60,
    )


def test_report_holder_with_a_working_subagent_is_not_idle(test_db) -> None:
    [holder] = _holders(seed_steering_scope(test_db), "subagent-parent", JUST_NOW)

    assert holder.last_activity_at == parse_instant(JUST_NOW)
    assert holder.session_state["activity"] != "silent"
    assert quiet_holders((holder,)) == ()


def test_report_holder_whose_subagent_is_stale_stays_idle(test_db) -> None:
    [holder] = _holders(seed_steering_scope(test_db), "stale-parent", LONG_AGO)

    assert holder.session_state["activity"] == "silent"
    assert quiet_holders((holder,)) == (holder,)


def test_roster_counts_subagent_calls_as_session_activity(test_db) -> None:
    child_at = _iso()
    _insert_session(
        test_db, "roster-parent", last_heartbeat=_iso(60), last_tool_call_at=_iso(60)
    )
    test_db.execute(
        "UPDATE harness_sessions SET last_child_tool_call_at=%s "
        "WHERE session_id='roster-parent'",
        (child_at,),
    )
    test_db.commit()

    [row] = [r for r in list_sessions(limit=50) if r["session_id"] == "roster-parent"]

    assert row["session_state"]["activity"] != "silent"
    assert parse_instant(row["activity_at"]) == parse_instant(child_at)
