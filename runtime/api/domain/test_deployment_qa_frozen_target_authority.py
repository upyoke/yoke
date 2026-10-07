"""Mid-execution deployment QA checks compare against the frozen stage target."""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_execution_target import (
    validate_deployment_execution_target,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_authority import require_plan_execution_owner
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_requirement_target_rebind import rebind_requirement

SESSION = "frozen-target-walker"


def _materialized_stage(conn: Any, run_id: str, member: int) -> None:
    plan_id = _plan(conn, f"{run_id}-smoke")
    _seed_run(conn, run_id=run_id, stages=_stages(plan_id), members=(member,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
    )


def _edit_stage_settings(conn: Any, settings: dict[str, Any]) -> None:
    conn.execute(
        "UPDATE environments SET settings=%s WHERE project_id=1 AND name='stage'",
        (json.dumps(settings),),
    )
    conn.commit()


def _begin(conn: Any, run_id: str, member: int) -> dict[str, Any]:
    return begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=member,
        actor_id="2",
        session_id=SESSION,
    )


def _heartbeat_authority(conn: Any, execution: dict[str, Any], run_id: str) -> None:
    require_plan_execution_owner(
        execution,
        conn=conn,
        deployment_run_id=run_id,
        actor_id="2",
        session_id=SESSION,
    )


def test_environment_settings_edit_mid_stage_keeps_the_execution_valid(test_db):
    run_id = "run-frozen-target-settings-edit"
    _materialized_stage(test_db, run_id, 9811)
    execution = _begin(test_db, run_id, 9811)

    _edit_stage_settings(
        test_db,
        {
            "hosts": {"api": "https://api.changed.example.test"},
            "distribution": {"channel": "edited-mid-stage"},
        },
    )

    _heartbeat_authority(test_db, execution, run_id)
    validate_deployment_execution_target(test_db, execution)


def test_rebound_deployment_requirement_passes_begin_and_heartbeat(test_db):
    run_id = "run-frozen-target-rebind"
    _materialized_stage(test_db, run_id, 9812)
    _edit_stage_settings(test_db, {"distribution": {"channel": "corrected"}})
    requirement_ids = [
        int(row[0])
        for row in test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s",
            (run_id,),
        ).fetchall()
    ]
    assert requirement_ids
    for requirement_id in requirement_ids:
        result = rebind_requirement(
            test_db,
            requirement_id=requirement_id,
            rationale="distribution channel corrected on the same environment",
            actor_id=2,
        )
        assert result["already_current"] is False
    rebound = json.loads(
        test_db.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_ids[0],),
        ).fetchone()[0]
    )
    assert "role" not in rebound
    assert rebound["endpoints"]["release_channel"] == "corrected"

    execution = _begin(test_db, run_id, 9812)

    _heartbeat_authority(test_db, execution, run_id)
    validate_deployment_execution_target(test_db, execution)
