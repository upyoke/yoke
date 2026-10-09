"""A run freezes its members before the release that adds new columns boots.

The release's own run starts in-process against the authoritative database
while that database still has the previous release's schema, so the freeze
must read a column the database has not gained yet as absent, not refuse.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts.timestamps import parse_instant

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


@pytest.mark.parametrize("admission", ["plan", "direct"])
def test_a_run_materializes_and_executes_its_qa_on_an_unconverged_schema(
    test_db, monkeypatch, admission
):
    from runtime.api.domain.test_deployment_qa_stage_execution import (
        _plan as _command_plan,
    )
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.handlers.qa_requirement_insert import (
        RequirementSubject,
        execute_insert,
    )
    from yoke_core.domain.qa_plan_case_currency import plan_case_divergence
    from yoke_core.domain.qa_plan_edit import _current_cases
    from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
    from yoke_core.domain.qa_plan_management import replace_plan_cases
    from yoke_core.domain.qa_constants import requirement_select

    _isolate_status_effects(monkeypatch)
    plan_owned = admission == "plan"
    plan_id = _command_plan(test_db, f"unconverged-{admission}")
    monkeypatch.setattr(delivery, "_plan", lambda *_args: plan_id)
    run_id = f"run-unconverged-{admission}"
    delivery._seed_final_run(test_db, run_id, shared_qa=False)
    member = delivery.MEMBER_A
    source_id = _original_requirement(
        test_db, item_id=member, method_id="browser-inspection"
    )
    test_db.execute(
        "UPDATE qa_requirements SET target_env='prod',workflow_transition_id='release',"
        "plan_id=%s,plan_case_key=%s WHERE id=%s",
        (
            plan_id if plan_owned else None,
            "command-smoke" if plan_owned else None,
            source_id,
        ),
    )
    test_db.execute(f"ALTER TABLE qa_requirements {_NEW_COLUMNS}")
    test_db.execute(f"ALTER TABLE qa_plan_cases {_NEW_COLUMNS}")
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (
            snapshot_member_requirements(
                test_db,
                run_id=run_id,
                item_id=member,
                selection_json=requirement_selection(requirement_ids=(source_id,)),
            ),
            run_id,
            member,
        ),
    )
    test_db.commit()

    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=f"qa-unconverged-{admission}",
    )
    copy_id = int(execution["roster"][0]["requirement_id"])
    assert materialized["created_requirement_ids"]
    assert test_db.execute(
        f"SELECT {requirement_select(test_db)} FROM qa_requirements WHERE id=%s",
        (copy_id,),
    ).fetchone()
    assert plan_case_divergence(test_db, copy_id) is None
    added = execute_insert(
        test_db,
        RequirementSubject.for_item(member),
        {"qa_kind": "ac_verification", "qa_phase": "verification"},
        parse_instant("2026-10-07T00:00:00Z"),
    ).fetchone()
    assert added
    cases = _current_cases(test_db, plan_id)
    assert cases and cases[0]["starting_state"] is None
    replace_plan_cases(test_db, plan_id=plan_id, cases=cases)
