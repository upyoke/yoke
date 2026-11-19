"""A parked claim holder's fleet line names its next scheduled recheck."""

from datetime import datetime, timedelta, timezone

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.session_scheduled_wake import recheck_label
from yoke_core.domain.steering_fleet_report_holders import ClaimHolder
from yoke_core.domain.steering_fleet_report_projection import _holder_dict
from yoke_core.domain.steering_fleet_report_render_holders import holder_lines

PARKED = {"intent": {"state": "parked", "reason": "waiting on prod traffic"}}


def _holder(**kwargs) -> ClaimHolder:
    return ClaimHolder(
        session_id="parked-holder",
        item_id=1,
        public_ref="YOK-1",
        mode="wait",
        parked=True,
        last_activity_at=datetime(2026, 11, 19, tzinfo=timezone.utc),
        idle_seconds=600,
        session_state=PARKED,
        **kwargs,
    )


def test_parked_holder_line_carries_the_recheck_after_its_reason():
    due = utc_now() + timedelta(hours=3)
    holder = _holder(next_recheck_at=due)

    (line,) = holder_lines((holder,))

    label = recheck_label(due, now=utc_now())
    assert f", parked — waiting on prod traffic, next recheck {label}" in line
    assert _holder_dict(holder)["next_recheck_at"] == due


def test_holder_without_a_recheck_has_no_suffix():
    (line,) = holder_lines((_holder(),))

    assert "next recheck" not in line
    assert _holder_dict(_holder())["next_recheck_at"] is None


def test_claim_holders_read_the_earliest_pending_recheck_in_one_statement(test_db):
    from runtime.api.fixtures.statement_counter import CountingConnection
    from runtime.api.steering_fleet_test_helpers import (
        ACTOR_ID,
        NOW,
        PROJECT_ID,
        WORKER_SESSION,
        seed_steering_scope,
    )
    from yoke_contracts.timestamps import parse_instant
    from yoke_core.domain.session_scheduled_wake import schedule_session_wake
    from yoke_core.domain.sessions_lifecycle_claim import claim_work
    from yoke_core.domain.steering_fleet_report_holders import claim_holders
    from yoke_core.domain.work_claim_targets import make_item_target

    conn = seed_steering_scope(test_db)
    claim_work(conn, session_id=WORKER_SESSION, target=make_item_target(1))
    now = parse_instant(NOW)
    for hours in (5, 2):
        schedule_session_wake(
            conn,
            session_id=WORKER_SESSION,
            actor_id=ACTOR_ID,
            at=now + timedelta(hours=hours),
            reason=f"recheck in {hours}h",
            now=now,
        )
    conn.commit()
    counted = CountingConnection(conn)

    (holder,) = claim_holders(counted, project_id=PROJECT_ID, now=NOW)

    assert holder.next_recheck_at == now + timedelta(hours=2)
    assert counted.count == 1
