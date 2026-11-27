"""A live member execution owns only the cases its frozen roster holds.

Two disjoint partitions of one member share a run and stage. The partition
whose walk awaits review owns its own case; the sibling's case has no live
custody, so its line names the run recipe instead of that execution.
"""

from __future__ import annotations

import json

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_live_executions import covering_execution
from yoke_core.domain.deployment_qa_stage_case_failures import case_failures
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

RUN = "run-partition-coverage"
MEMBER = 9761
KEYS = ("partition-one", "partition-two")


def _two_case_plan(conn) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug="partitioned-smoke",
        name="Partitioned smoke",
        infer_target_environment=False,
    )
    replace_plan_cases(
        conn,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": f"run {key}",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
                "target_envs": [],
            }
            for position, key in enumerate(KEYS, start=1)
        ],
    )
    return int(plan["id"])


def _one_partition_awaiting_review(conn) -> tuple[dict, int, int]:
    stages = _stages(_two_case_plan(conn))
    stages[1]["cases"]["case_keys"] = list(KEYS)
    _seed_run(conn, run_id=RUN, stages=stages, members=(MEMBER,))
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="partition-one-walk",
    )
    owned, sibling = (int(case["requirement_id"]) for case in execution["roster"])
    # Freeze the walk to its own partition, as the partition planner does,
    # and hand it back for review.
    conn.execute(
        "UPDATE qa_plan_executions SET roster_json=%s, state='awaiting_walk_review' "
        "WHERE id=%s",
        (json.dumps([execution["roster"][0]]), execution["id"]),
    )
    conn.commit()
    return execution, owned, sibling


def test_awaiting_review_partition_leaves_its_sibling_runnable(test_db) -> None:
    execution, owned, sibling = _one_partition_awaiting_review(test_db)
    failures = {
        failure.requirement_id: failure.detail
        for failure in case_failures(
            test_db,
            run_id=RUN,
            stage_name="item-qa",
            member_item_id=MEMBER,
            execution_target_digest=execution["execution_target_digest"],
        )
    }
    assert set(failures) == {owned, sibling}
    holder = f"plan execution {execution['id']} (awaiting_walk_review) already owns it"
    assert holder in failures[owned]
    assert holder not in failures[sibling]
    assert execution["id"] not in failures[sibling]
    assert f"run `yoke qa case run --requirement-id {sibling}`" in failures[sibling]


def test_member_coverage_without_a_case_still_names_the_live_walk(test_db) -> None:
    execution, owned, sibling = _one_partition_awaiting_review(test_db)
    scope = {
        "run_id": RUN,
        "stage_name": "item-qa",
        "member_item_id": MEMBER,
        "execution_target_digest": execution["execution_target_digest"],
    }
    # Member-level reporting asks without a case and still sees the walk.
    assert covering_execution(test_db, **scope)["execution_id"] == execution["id"]
    assert (
        covering_execution(test_db, **scope, requirement_id=owned)["execution_id"]
        == execution["id"]
    )
    assert covering_execution(test_db, **scope, requirement_id=sibling) is None
