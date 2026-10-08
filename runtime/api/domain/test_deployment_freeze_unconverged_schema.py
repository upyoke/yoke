"""A run freezes its members before the release that adds new columns boots.

The release's own run starts in-process against the authoritative database
while that database still has the previous release's schema, so the freeze
must read a column the database has not gained yet as absent, not refuse.
"""

from __future__ import annotations

import json

from runtime.api.domain import test_independent_member_delivery_close_out as delivery
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_status_transition_preflight import _isolate_status_effects
from yoke_core.domain.deployment_requirement_snapshots import (
    _plan_snapshot,
    requirement_selection,
    snapshot_member_requirements,
)

_NEW_COLUMNS = "DROP COLUMN starting_state, DROP COLUMN starting_state_reason"


def test_freeze_reads_a_database_without_the_starting_state_columns(
    test_db, monkeypatch
):
    _isolate_status_effects(monkeypatch)
    plan_id = _plan(test_db, "unconverged-freeze")
    run_id = "run-unconverged-freeze"
    delivery._seed_final_run(test_db, run_id, shared_qa=False)
    member = delivery.MEMBER_A
    source_id = _original_requirement(
        test_db, item_id=member, method_id="browser-inspection"
    )
    test_db.execute(
        "UPDATE qa_requirements SET target_env='prod',"
        "workflow_transition_id='release' WHERE id=%s",
        (source_id,),
    )
    # The authoritative database still carries the previous release's schema.
    test_db.execute(f"ALTER TABLE qa_requirements {_NEW_COLUMNS}")
    test_db.execute(f"ALTER TABLE qa_plan_cases {_NEW_COLUMNS}")

    frozen = json.loads(
        snapshot_member_requirements(
            test_db,
            run_id=run_id,
            item_id=member,
            selection_json=requirement_selection(requirement_ids=(source_id,)),
        )
    )
    plan = _plan_snapshot(test_db, plan_id, project_id=1)

    requirements = [
        entry for entry in frozen["requirements"] if int(entry["id"]) == source_id
    ]
    assert requirements and requirements[0]["starting_state"] is None
    assert plan["cases"] and all(
        case["starting_state"] is None and case["starting_state_reason"] is None
        for case in plan["cases"]
    )
