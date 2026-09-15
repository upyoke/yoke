"""Human verdict policies follow scoped case evidence, never precede it."""

import json

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review


def _human_actor(test_db, actor_id: int) -> None:
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (actor_id,),
    )


def _agent_review_plan(test_db) -> int:
    plan = create_plan(
        test_db,
        project="yoke",
        slug="unsure-release-smoke",
        name="Unsure release smoke",
        infer_target_environment=False,
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "browser-inspection",
                "instructions": "Inspect the deployed release.",
                "expected_outcome": "The expected release is visible.",
                "method_config": {
                    "steps": [
                        {"action": "navigate", "route": "/releases/current"},
                        {"action": "screenshot", "capture": True},
                    ]
                },
            }
        ],
    )
    return int(plan["id"])


def test_required_human_request_waits_for_exact_case_evidence(test_db) -> None:
    reviewer = 9799
    _human_actor(test_db, reviewer)
    plan_id = _plan(test_db, "human-release-smoke")
    reviewers = {"mode": "all", "roles": [], "actors": [reviewer]}
    stages = _stages(
        plan_id,
        verdict={"mode": "required_human", "reviewers": reviewers},
    )
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id="run-human-stage", stages=stages, members=())
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-human-stage",
        deployment_stage="item-qa",
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-human-stage",
        deployment_stage="item-qa",
        actor_id="2",
        session_id="run-qa",
    )
    before = deployment_qa_stage_status(
        test_db,
        run_id="run-human-stage",
        stage_name="item-qa",
        member_item_id=None,
    )
    assert not before["accepted"] and before["request_id"] is None

    requirement_id = _complete_case(test_db, execution)
    run_id = int(
        test_db.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id DESC LIMIT 1",
            (requirement_id,),
        ).fetchone()[0]
    )
    test_db.execute("DELETE FROM qa_artifacts WHERE qa_run_id=%s", (run_id,))
    test_db.commit()
    without_evidence = deployment_qa_stage_status(
        test_db,
        run_id="run-human-stage",
        stage_name="item-qa",
        member_item_id=None,
    )
    assert without_evidence["request_id"] is None
    assert any("no attached evidence" in reason for reason in without_evidence["reasons"])

    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'log','evidence://human-stage','2026-09-14T00:03:00Z')",
        (run_id,),
    )
    test_db.commit()
    pending = deployment_qa_stage_status(
        test_db,
        run_id="run-human-stage",
        stage_name="item-qa",
        member_item_id=None,
    )
    assert not pending["accepted"] and pending["request_id"] is not None
    resolve_decision_request(
        test_db,
        int(pending["request_id"]),
        actor_id=reviewer,
        action="approve",
        note="Exact scoped evidence satisfies the stage policy.",
    )
    assert deployment_qa_stage_status(
        test_db,
        run_id="run-human-stage",
        stage_name="item-qa",
        member_item_id=None,
    )["accepted"]


def test_human_if_unsure_waits_for_authorized_case_decision(test_db) -> None:
    reviewer = 9798
    _human_actor(test_db, reviewer)
    plan_id = _agent_review_plan(test_db)
    reviewers = {"mode": "any", "roles": [], "actors": [reviewer]}
    stages = _stages(
        plan_id,
        verdict={"mode": "human_if_unsure", "reviewers": reviewers},
    )
    stages[1]["scope"] = "run"
    _seed_run(test_db, run_id="run-unsure-stage", stages=stages, members=())
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-unsure-stage",
        deployment_stage="item-qa",
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id="run-unsure-stage",
        deployment_stage="item-qa",
        actor_id="2",
        session_id="unsure-run-qa",
    )
    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-14T00:02:00Z"
    capture_run_id = int(
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
            "case_outcome,raw_result,started_at,completed_at,created_at) VALUES "
            "(%s,'host_control','plan_case','needs_review',%s,%s,%s,%s) RETURNING id",
            (requirement_id, json.dumps({"evidence": "ambiguous"}), now, now, now),
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'screenshot','evidence://unsure-stage',%s)",
        (capture_run_id, now),
    )
    advance_plan_execution(
        test_db,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "runner_id": "browser_substrate",
            "verdict": None,
            "case_outcome": "needs_review",
            "qa_run_id": capture_run_id,
        },
    )
    bundle = begin_plan_review(test_db, execution)
    result = submit_plan_review(
        test_db,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": "undetermined",
                "rationale": "The captured release state needs human judgment.",
            }
        ],
        reviewer_actor_id="2",
        reviewer_session_id="unsure-run-qa",
    )
    request_id = int(result["verdicts"][0]["decision_request_id"])
    assert not deployment_qa_stage_status(
        test_db,
        run_id="run-unsure-stage",
        stage_name="item-qa",
        member_item_id=None,
    )["accepted"]
    resolve_decision_request(
        test_db,
        request_id,
        actor_id=reviewer,
        action="approve",
        note="The evidence shows the intended release.",
    )
    assert deployment_qa_stage_status(
        test_db,
        run_id="run-unsure-stage",
        stage_name="item-qa",
        member_item_id=None,
    )["accepted"]
