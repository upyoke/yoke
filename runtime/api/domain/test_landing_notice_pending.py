"""A freshly landed holder is not idle until it has acted on the landing notice.

The landing observer messages the claim holder after a queued PR merges.
Between the merge and the holder's first action after that notice, the
holder's silence is the notice in flight, so neither the steering report nor
the idle-holder alarm treats it as idle.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.steering_fleet_test_helpers import (
    BEFORE_THAT,
    JUST_NOW,
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
    seed_steering_scope,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.fleet_delta_alarms import DeltaState, idle_holder_alarms
from yoke_core.domain.fleet_delta_snapshot import (
    ENVELOPES_FUNCTION,
    FRONTIER_FUNCTION,
    SESSIONS_FUNCTION,
    read_snapshot,
)
from yoke_core.domain.sessions_holdings_claim_facts import (
    ITEM_AWAITING_LANDING_KEY,
    claimed_item_facts,
)
from yoke_core.domain.steering_fleet_report_holders import claim_holders
from yoke_core.domain.turn_end_unfinished_work import landing_notice_pending
from yoke_core.domain.work_claim_targets import make_item_target

HOLDER = "landed-worker"
LANDED = {
    "status": "reviewing-implementation",
    "merge_queue_landed_at": BEFORE_THAT,
    "merge_queue_notified_at": LONG_AGO,
}


@pytest.mark.parametrize(
    "overrides, pending",
    [
        ({}, True),
        ({"last_tool_call_at": BEFORE_THAT}, True),
        ({"merge_queue_notified_at": None}, False),
        ({"last_tool_call_at": JUST_NOW}, False),
        ({"merge_queue_landed_at": None}, False),
        ({"status": "done"}, False),
    ],
)
def test_pending_until_the_holder_acts_after_the_notice(overrides, pending):
    assert landing_notice_pending({**LANDED, **overrides}) is pending


def _claim(conn, session_id: str, item_id: int) -> None:
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (%s,%s,%s,'exclusive',%s,%s)",
        (session_id, target.kind, target.scope_json(), BEFORE_THAT, BEFORE_THAT),
    )
    conn.commit()


def _alarms_for(awaiting_landing: bool) -> list[str]:
    """The idle-holder alarm for a holder silent an hour, given its roster flag."""
    now = parse_instant(NOW)

    def call(function, payload):
        rows = [
            {
                "session_id": HOLDER,
                "mode": "dash",
                "activity_at": (now - timedelta(hours=1)).isoformat(),
                "claims": [
                    {
                        "target_kind": "item",
                        "target": "YOK-1",
                        ITEM_AWAITING_LANDING_KEY: awaiting_landing,
                    }
                ],
            }
        ]
        results = {
            SESSIONS_FUNCTION: {"rows": rows},
            FRONTIER_FUNCTION: {},
            ENVELOPES_FUNCTION: {},
        }
        return SimpleNamespace(success=True, result=results[function])

    snapshot = read_snapshot(["project"], call=call, now=now, self_session_id="seat")
    return idle_holder_alarms(snapshot, DeltaState())


def test_an_alarm_is_suppressed_until_the_holder_acts_after_the_notice(
    test_db,
) -> None:
    fleet = seed_steering_scope(test_db)
    seed_session(fleet, HOLDER, last_tool_call_at=BEFORE_THAT)
    fleet.execute(
        "UPDATE items SET status='reviewing-implementation', "
        "merge_queue_pr_number='7', merge_queue_enqueued_at=%s, merge_queue_landed_at=%s, "
        "merge_queue_notified_at=%s WHERE id=1",
        (BEFORE_THAT, BEFORE_THAT, LONG_AGO),
    )
    _claim(fleet, HOLDER, 1)

    holder = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)[0]
    awaiting = claimed_item_facts(fleet, [1])[1][ITEM_AWAITING_LANDING_KEY]
    assert holder.landing_notice_pending and awaiting
    assert _alarms_for(awaiting) == []

    fleet.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s WHERE session_id=%s",
        (JUST_NOW, HOLDER),
    )
    fleet.commit()

    holder = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)[0]
    awaiting = claimed_item_facts(fleet, [1])[1][ITEM_AWAITING_LANDING_KEY]
    assert not holder.landing_notice_pending and not awaiting
    assert "ALARM idle-holder" in _alarms_for(awaiting)[0]
