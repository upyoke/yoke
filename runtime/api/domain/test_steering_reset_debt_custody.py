"""Steering preserves live walk custody when teaching reset recovery."""

import pytest

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from yoke_core.domain.machine_reset_debt import record_reset_owed
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_STATES
from yoke_core.domain.steering_fleet_report_test_machines import (
    read_reset_debts,
    reset_debt_lines,
)


removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("companion", [False, True])
@pytest.mark.parametrize("state", sorted(LIVE_PLAN_EXECUTION_STATES))
def test_live_walk_debt_names_execution_without_recovery(
    test_db, removed_mission, companion, state
):
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_render import report_body

    request, _, contract = removed_mission
    execution_id = request.payload["execution_id"]
    lease_id = contract["lease_id"]
    machine = contract["settings"]["resource_name"]
    test_db.execute(
        "UPDATE qa_plan_executions SET state=%s WHERE id=%s", (state, execution_id)
    )
    if companion:
        test_db.execute(
            "UPDATE work_claims SET reason=%s WHERE id=%s",
            ("qa-plan-hosts:" + execution_id, lease_id),
        )
        test_db.execute(
            "UPDATE qa_plan_executions SET machine_lease_id=NULL WHERE id=%s",
            (execution_id,),
        )
    record_reset_owed(
        test_db,
        case={"project_id": 1, "host_baseline": "fresh-host"},
        machine=machine,
        lease_id=lease_id,
    )
    test_db.commit()
    rows = read_reset_debts(test_db, 1)
    assert rows[0].execution_id == execution_id
    assert rows[0].recovery is None
    assert reset_debt_lines(rows) == [
        f"Test Machine {machine}: reset owed after {execution_id}"
    ]
    seed_steering_scope(test_db)
    report = compose(test_db)
    assert report_dict(report)["reset_debts"] == [
        {"machine": machine, "recovery": None, "execution_id": execution_id}
    ]
    assert "reset owed after " + execution_id in report_body(report)
    assert "yoke test-machine reset" not in report_body(report)
    held_fingerprint = report.fingerprint()
    test_db.execute(
        "UPDATE work_claims SET released_at=CURRENT_TIMESTAMP WHERE id=%s", (lease_id,)
    )
    test_db.commit()
    released = compose(test_db)
    assert released.fingerprint() != held_fingerprint
    assert "machine_needs_repair" in report_body(released)
    assert "yoke test-machine reset" in report_body(released)


def test_terminal_execution_does_not_hide_reset_recovery(test_db, removed_mission):
    request, _, contract = removed_mission
    machine = contract["settings"]["resource_name"]
    record_reset_owed(
        test_db,
        case={"project_id": 1, "host_baseline": "fresh-host"},
        machine=machine,
        lease_id=contract["lease_id"],
    )
    test_db.execute(
        "UPDATE qa_plan_executions SET state='completed' WHERE id=%s",
        (request.payload["execution_id"],),
    )
    rows = read_reset_debts(test_db, 1)
    assert rows[0].execution_id is None
    assert "machine_needs_repair" in reset_debt_lines(rows)[0]
