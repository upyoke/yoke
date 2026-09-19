"""An admitted plan-less QA copy begins on its runner instead of refusing.

Deployment admission copies a member's frozen post-deploy obligation onto the
stage subject as a row belonging to no plan. When that copy carried plan
positions, the drift check every ``test_machine.plan_case.begin`` runs read
them as "this requirement joined a plan after the roster froze" and refused
the case -- and refused it permanently, because the rebuilt roster an
abort-and-restart produces reads the same row back.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
)
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

RUN_ID = "run-admitted-mission"
STAGE = "member-qa"
ITEM_ID = 9714
#: One of the sessions the shared test-machine fixture registers, so the
#: coordination claim this begin takes reads a real actor off its session row.
SESSION_ID = "session-agent-mission"
ACTOR = ActorContext(actor_id="2", session_id=SESSION_ID)


def _mission_obligation(conn: Any, *, item_id: int) -> int:
    """The member's own post-deploy exploratory-mission requirement."""
    method = conn.execute(
        "SELECT name,runner_id,required_capability_kinds,verdict_path "
        "FROM qa_methods WHERE id='exploratory-mission'"
    ).fetchone()
    row = conn.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,target_env,"
        "blocking_mode,requirement_source,instructions,expected_outcome,"
        "created_at,method_id,method_name,runner_id,capability_requirements,"
        "verdict_path,method_config) VALUES "
        "(%s,'acceptance','post_deploy','stage','blocking','explicit',%s,%s,"
        "%s,'exploratory-mission',%s,%s,%s,%s,%s) RETURNING id",
        (
            item_id,
            "Walk the deployed release as a new user and rank what blocks them.",
            "Ranked actionable findings, naming anything that could not be checked.",
            "2026-09-14T00:00:00Z",
            method["name"],
            method["runner_id"],
            method["required_capability_kinds"],
            method["verdict_path"],
            json.dumps({"executor": "naive_target_session"}),
        ),
    ).fetchone()
    conn.commit()
    return int(row["id"])


@pytest.fixture
def admitted_mission_requirement(test_db, tmp_path, monkeypatch) -> int:
    """The materialized admitted copy of that obligation, ready to execute."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    insert_item(
        test_db, id=ITEM_ID, project_sequence=714, workflow_id="issue", status="done"
    )
    original_id = _mission_obligation(test_db, item_id=ITEM_ID)
    _seed_selected_requirement_run(
        test_db, run_id=RUN_ID, item_id=ITEM_ID, requirement_id=original_id
    )
    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN_ID,
        deployment_stage=STAGE,
        deployment_member_item_id=ITEM_ID,
    )
    return int(materialized["created_requirement_ids"][0])


def test_an_admitted_copy_stores_no_position_of_its_own(
    test_db, admitted_mission_requirement
) -> None:
    row = test_db.execute(
        "SELECT plan_id,case_position,baseline_position FROM qa_requirements "
        "WHERE id=%s",
        (admitted_mission_requirement,),
    ).fetchone()

    assert row["plan_id"] is None
    assert row["case_position"] is None
    assert row["baseline_position"] is None


def test_an_admitted_mission_copy_begins_without_a_roster_drift_refusal(
    test_db, admitted_mission_requirement
) -> None:
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN_ID,
        deployment_stage=STAGE,
        deployment_member_item_id=ITEM_ID,
        actor_id=ACTOR.actor_id,
        session_id=SESSION_ID,
    )
    assert execution["roster"][0]["plan_id"] is None
    assert execution["roster"][0]["runner_id"] == "agent_mission"

    begun = handle_plan_case_begin(
        FunctionCallRequest(
            function="test_machine.plan_case.begin",
            actor=ACTOR,
            target=TargetRef(kind="deployment_run", deployment_run_id=RUN_ID),
            payload={
                "execution_id": str(execution["id"]),
                "requirement_id": admitted_mission_requirement,
                "ordinal": 0,
            },
        )
    )

    assert begun.primary_success, begun.error
