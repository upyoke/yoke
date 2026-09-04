"""Hand-started workers remain explicit in fleet staffing facts."""

from __future__ import annotations

from runtime.api.steering_fleet_test_helpers import (
    NOW,
    PROJECT_ID,
    STEERING_SESSION,
    seed_steering_scope,
)
from yoke_core.domain.steering_fleet_report_capacity import (
    MANUAL_SESSION_ORIGIN,
    live_launch_origin_counts,
)
from yoke_core.domain.steering_fleet_report_holders import claim_holders
from yoke_core.domain.work_claim_targets import make_item_target


def test_unbound_live_sessions_count_as_manual_and_holders_name_the_fact(
    test_db,
) -> None:
    fleet = seed_steering_scope(test_db)
    target = make_item_target(1)
    fleet.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat) "
        "VALUES (%s,%s,%s,'exclusive',%s,%s)",
        (STEERING_SESSION, target.kind, target.scope_json(), NOW, NOW),
    )
    fleet.commit()

    counts = dict(live_launch_origin_counts(fleet, project_id=PROJECT_ID))
    holders = claim_holders(fleet, project_id=PROJECT_ID, now=NOW)

    assert counts[MANUAL_SESSION_ORIGIN] == 2
    assert len(holders) == 1
    assert holders[0].hand_started is True
