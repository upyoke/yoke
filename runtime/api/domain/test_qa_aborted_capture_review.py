"""A partial terminated walk keeps immutable review authority for completed captures."""

import pytest

from runtime.api.fixtures.qa_captured_plan_review_fixture import captured_plan_review
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_review import (
    handle_plan_review_begin,
    handle_plan_review_submit,
)
from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
from yoke_core.domain.qa_plan_execution_store import lock_plan_execution


@pytest.mark.parametrize("disposition", ["failed", "cancelled"])
def test_closed_deployment_still_authorizes_its_bound_capture_review(
    test_db, disposition
):
    import json
    from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run, _stages
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
    from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject
    from yoke_core.domain.qa_plan_execution_state import (
        begin_plan_execution,
        advance_plan_execution,
    )

    item_id, run_id = 9781, "run-review-after-closure"
    _, original, _ = captured_plan_review(test_db, item_id)
    plan_id = int(
        test_db.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=%s", (original,)
        ).fetchone()[0]
    )
    stages = _stages(plan_id)
    stages[1]["cases"]["case_keys"] = ["review-frame"]
    _seed_run(
        test_db, run_id=run_id, stages=stages, members=(), existing_members=(item_id,)
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        actor_id="7",
        session_id="review-session",
    )
    requirement = int(execution["roster"][0]["requirement_id"])
    capture = int(
        test_db.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,case_outcome,execution_status,started_at,completed_at,created_at) "
            "VALUES (%s,'host_control','plan_case','needs_review','captured','2026-09-14T00:02:00Z','2026-09-14T00:03:00Z','2026-09-14T00:02:00Z') RETURNING id",
            (requirement,),
        ).fetchone()[0]
    )
    test_db.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) VALUES (%s,'terminal_screenshot',%s,'2026-09-14T00:03:00Z')",
        (capture, json.dumps({"backend": "local", "path": "/tmp/closed-capture.png"})),
    )
    advance_plan_execution(
        test_db,
        execution,
        ordinal=0,
        requirement_id=requirement,
        result={
            "requirement_id": requirement,
            "run_id": capture,
            "verdict": None,
            "case_outcome": "needs_review",
        },
    )
    terminalize_run_on(
        test_db,
        run_id,
        disposition=disposition,
        reason="runner failed",
        actor_id=None,
        session_id="driver",
    )
    test_db.commit()
    actor = ActorContext(actor_id="7", session_id="review-session")
    target = TargetRef(kind="deployment_run", deployment_run_id=run_id)
    request = FunctionCallRequest(
        function="qa.plan_review.begin",
        actor=actor,
        target=target,
        payload={"execution_id": execution["id"]},
    )
    assert resolve_run_qa_subject(test_db, request)[2] == item_id
    begun = handle_plan_review_begin(request)
    assert begun.primary_success, begun.error
    bundle = begun.result_payload["review_bundle"]
    submitted = handle_plan_review_submit(
        FunctionCallRequest(
            function="qa.plan_review.submit",
            actor=actor,
            target=target,
            payload={
                "execution_id": execution["id"],
                "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"],
                "verdicts": [
                    {
                        "requirement_id": requirement,
                        "verdict": "pass",
                        "rationale": "The completed capture is correct.",
                    }
                ],
            },
        )
    )
    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["state"] == "aborted"
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == disposition
    )
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (capture,)
        ).fetchone()[0]
        == "pass"
    )


@pytest.mark.parametrize("state", ["aborted", "error"])
def test_partial_terminal_walk_can_review_completed_capture_without_reopening(
    test_db, state
):
    item_id = 9780
    execution, requirement_id, capture_id = captured_plan_review(
        test_db, item_id, unfinished_case=True
    )
    assert execution["cursor_ordinal"] == 1 and len(execution["roster"]) == 2
    finish_plan_execution(test_db, execution, state=state, reason="second case failed")
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()[0]
        is None
    )
    actor = ActorContext(actor_id="7", session_id="review-session")
    target = TargetRef(kind="item", item_id=item_id)
    begun = handle_plan_review_begin(
        FunctionCallRequest(
            function="qa.plan_review.begin",
            actor=actor,
            target=target,
            payload={"execution_id": execution["id"]},
        )
    )
    assert begun.primary_success, begun.error
    bundle = begun.result_payload["review_bundle"]
    assert [case["capture_run_id"] for case in bundle["cases"]] == [capture_id]
    submitted = handle_plan_review_submit(
        FunctionCallRequest(
            function="qa.plan_review.submit",
            actor=actor,
            target=target,
            payload={
                "execution_id": execution["id"],
                "bundle_id": bundle["bundle_id"],
                "bundle_digest": bundle["bundle_digest"],
                "verdicts": [
                    {
                        "requirement_id": requirement_id,
                        "verdict": "pass",
                        "rationale": "The completed frame is correct.",
                    }
                ],
            },
        )
    )
    assert submitted.primary_success, submitted.error
    assert submitted.result_payload["state"] == state
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (capture_id,)
        ).fetchone()[0]
        == "pass"
    )
    assert lock_plan_execution(test_db, execution["id"])["state"] == state
    unwalked = int(execution["roster"][1]["requirement_id"])
    assert (
        test_db.execute(
            "SELECT 1 FROM qa_runs WHERE qa_requirement_id=%s", (unwalked,)
        ).fetchone()
        is None
    )


def test_failed_walk_review_lists_chain_blocked_cases_with_reasons(test_db):
    from yoke_core.domain.qa_plan_case_chain import INHERITED_PREDECESSOR_NOT_PASSED
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    item_id = 9782
    execution, requirement_id, capture_id = captured_plan_review(
        test_db, item_id, unfinished_case=True
    )
    blocked_case = execution["roster"][1]
    reason = "case 'follow' inherits the machine case 'anchor' left; it was not run"
    advance_plan_execution(
        test_db,
        execution,
        ordinal=1,
        requirement_id=int(blocked_case["requirement_id"]),
        result={
            "requirement_id": int(blocked_case["requirement_id"]),
            "case_outcome": "blocked_on_precondition",
            "verdict": "blocked",
            "error_code": INHERITED_PREDECESSOR_NOT_PASSED,
            "error": reason,
        },
    )
    finish_plan_execution(
        test_db,
        execution,
        state="aborted",
        reason="qa-plan-case-failed: requirements 1",
    )
    begun = handle_plan_review_begin(
        FunctionCallRequest(
            function="qa.plan_review.begin",
            actor=ActorContext(actor_id="7", session_id="review-session"),
            target=TargetRef(kind="item", item_id=item_id),
            payload={"execution_id": execution["id"]},
        )
    )
    assert begun.primary_success, begun.error
    bundle = begun.result_payload["review_bundle"]
    assert [case["capture_run_id"] for case in bundle["cases"]] == [capture_id]
    assert bundle["chain_blocked"] == [
        {
            "requirement_id": int(blocked_case["requirement_id"]),
            "case_key": str(blocked_case["case_key"]),
            "error_code": INHERITED_PREDECESSOR_NOT_PASSED,
            "reason": reason,
        }
    ]
