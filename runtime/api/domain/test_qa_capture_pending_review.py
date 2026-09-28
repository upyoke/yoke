"""A completed capture awaiting its independent review is not a QA pass.

A deployment QA stage whose case needs an agent verdict captures first and
then waits at ``awaiting_agent_review`` for the reviewer that submits the
bundle. In that window the capture-side session must not be able to write a
verdict of its own onto the requirement, and the stage must say "review
pending" rather than "never run". Once the reviewer submits, the existing
settlement takes over unchanged: a reviewed pass accepts the stage and a
reviewed fail blocks it. Each shape runs for a member-scoped stage and a
run-scoped stage.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    seed_run_standing_on_qa_stage,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_execution_target import (
    deployment_qa_execution_target,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_AWAITING_REVIEW,
    STAGE_CASES_UNRESOLVED,
    STAGE_NOT_RUN,
    stage_acceptance,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    deployment_qa_stage_subject,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers import qa_browser_writes, qa_run
from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_requirement,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.qa_plan_review import begin_plan_review
from yoke_core.domain.qa_plan_review_submission import submit_plan_review

STAGE = "prod-qa"
MEMBER = 9851
NOW = "2026-09-27T00:00:00Z"
PENDING_TEXT = "independent agent review is pending"


def _stages(plan_id: int, scope: str) -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": STAGE,
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": scope,
            "target": {
                "kind": "persistent_environment",
                "environment": "stage",
                "source_stage": "deploy",
            },
            "cases": {"plan_id": plan_id, "case_keys": ["command-smoke"]},
            "verdict": {"mode": "agent_only"},
        },
    ]


def _member(scope: str) -> int | None:
    return MEMBER if scope == "item" else None


def _seed_pending(conn: Any, run_id: str, scope: str) -> tuple[dict, dict, int]:
    """Stand one stage subject at a completed capture awaiting review."""
    member = _member(scope)
    plan_id = create_smoke_plan(conn, project="yoke", slug=f"smoke-{run_id}")
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=_stages(plan_id, scope),
        members=(MEMBER,),
        lineage="e" * 40,
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
    )
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND COALESCE(deployment_member_item_id,0)=%s "
        "AND method_id IS NOT NULL",
        (run_id, STAGE, member or 0),
    ).fetchone()
    requirement_id = int(row["id"])
    # The capture needs an independent verdict: an agent-reviewed inspection.
    conn.execute(
        "UPDATE qa_requirements SET method_id='browser-inspection',"
        "runner_id='browser_substrate',verdict_path='agent' WHERE id=%s",
        (requirement_id,),
    )
    conn.commit()
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=member,
        actor_id="2",
        session_id="capture-session",
    )
    capture_run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
            "execution_status,case_outcome,raw_result,started_at,completed_at,"
            "created_at) VALUES(%s,'browser_substrate','method_case','captured',"
            "'needs_review','{}',%s,%s,%s) RETURNING id",
            (requirement_id, NOW, NOW, NOW),
        ).fetchone()["id"]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES(%s,'screenshot','image/png',%s,%s)",
        (capture_run_id, json.dumps({"backend": "local", "path": "/tmp/p.png"}), NOW),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "runner_id": "browser_substrate",
            "verdict": "pending",
            "execution_status": "captured",
            "qa_run_id": capture_run_id,
            "run_id": capture_run_id,
        },
    )
    bundle = begin_plan_review(conn, execution)
    assert bundle is not None
    conn.commit()
    return execution, bundle, requirement_id


def _acceptance(conn: Any, run_id: str, scope: str):
    subject = deployment_qa_stage_subject(
        conn,
        run_id=run_id,
        stage_name=STAGE,
        member_item_id=_member(scope),
        require_active=False,
    )
    return stage_acceptance(
        conn,
        subject=subject,
        target=deployment_qa_execution_target(conn, subject),
        acceptance_qa_kind=DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
    )


def _submit(conn: Any, execution: dict, bundle: dict, requirement_id: int, verdict: str):
    submit_plan_review(
        conn,
        execution,
        bundle_id=bundle["bundle_id"],
        bundle_digest=bundle["bundle_digest"],
        verdicts=[
            {
                "requirement_id": requirement_id,
                "verdict": verdict,
                "rationale": f"Reviewed the capture: {verdict}.",
            }
        ],
        reviewer_actor_id=None,
        reviewer_session_id="reviewer-session",
    )
    conn.commit()


def _request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="capture-session"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def _capture_verdict(conn: Any, requirement_id: int) -> Any:
    return conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "AND performed_by='browser_substrate'",
        (requirement_id,),
    ).fetchone()["verdict"]


SCOPES = pytest.mark.parametrize("scope", ["item", "run"])


@SCOPES
def test_pending_review_reads_as_review_pending_not_never_run(test_db, scope) -> None:
    run_id = f"run-pending-{scope}"
    execution, bundle, _requirement = _seed_pending(test_db, run_id, scope)

    acceptance = _acceptance(test_db, run_id, scope)
    assert acceptance.state == STAGE_AWAITING_REVIEW != STAGE_NOT_RUN
    # The review-pending reason leads; the case line beside it says only
    # that no verdict exists yet, never that the case passed or failed.
    blocker, case_line = acceptance.blockers
    assert PENDING_TEXT in blocker
    assert case_line.endswith("latest verdict is missing")
    assert str(execution["id"]) in blocker and bundle["bundle_id"] in blocker
    assert "yoke qa plan review-submit" in blocker

    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=STAGE, member_item_id=_member(scope)
    )
    assert any(PENDING_TEXT in reason for reason in status["reasons"])
    assert not any(
        reason == "no completed scoped QA execution exists"
        for reason in status["reasons"]
    )


@SCOPES
def test_capture_side_verdicts_are_refused_while_review_is_pending(
    test_db, scope
) -> None:
    run_id = f"run-refuse-{scope}"
    _execution, _bundle, requirement_id = _seed_pending(test_db, run_id, scope)
    capture_run_id = int(
        test_db.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s", (requirement_id,)
        ).fetchone()["id"]
    )

    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        completed = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                requirement_id,
                {
                    "run_id": capture_run_id,
                    "verdict": "pass",
                    "verdict_reason": "Looked right to the capturing session.",
                    "execution_status": "captured",
                },
            )
        )
        recorded = qa_run.handle_qa_run_record_verdict(
            _request(
                "qa.run.record_verdict",
                requirement_id,
                {
                    "performed_by": "agent",
                    "verdict": "pass",
                    "verdict_reason": "Looked right to the capturing session.",
                },
            )
        )
        added = qa_browser_writes.handle_qa_run_add(
            _request(
                "qa.run.add",
                requirement_id,
                {"performed_by": "browser_substrate", "verdict": "pass"},
            )
        )

    for outcome in (completed, recorded, added):
        assert not outcome.primary_success
        assert outcome.error.code == "policy_violation"
        assert PENDING_TEXT in outcome.error.message
        assert "yoke qa plan review-submit" in outcome.error.message
    assert _capture_verdict(test_db, requirement_id) is None


@SCOPES
def test_reviewed_pass_accepts_the_stage(test_db, scope) -> None:
    run_id = f"run-pass-{scope}"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, scope)

    _submit(test_db, execution, bundle, requirement_id, "pass")

    assert pending_review_for_requirement(test_db, requirement_id) is None
    assert _capture_verdict(test_db, requirement_id) == "pass"
    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=STAGE, member_item_id=_member(scope)
    )
    assert not any(PENDING_TEXT in reason for reason in status["reasons"])
    assert _acceptance(test_db, run_id, scope).accepted


@SCOPES
def test_reviewed_fail_blocks_the_stage(test_db, scope) -> None:
    run_id = f"run-fail-{scope}"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, scope)

    _submit(test_db, execution, bundle, requirement_id, "fail")

    assert pending_review_for_requirement(test_db, requirement_id) is None
    assert _capture_verdict(test_db, requirement_id) == "fail"
    acceptance = _acceptance(test_db, run_id, scope)
    assert acceptance.state == STAGE_CASES_UNRESOLVED
    assert not any(PENDING_TEXT in reason for reason in acceptance.blockers)


def test_verdicts_on_requirements_with_no_pending_review_are_untouched(
    test_db,
) -> None:
    run_id = "run-no-review"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    _submit(test_db, execution, bundle, requirement_id, "pass")

    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        recorded = qa_run.handle_qa_run_record_verdict(
            _request(
                "qa.run.record_verdict",
                requirement_id,
                {
                    "performed_by": "human",
                    "verdict": "pass",
                    "verdict_reason": "Operator confirmation after review.",
                    "raw_result": json.dumps(
                        {"verification_tree": {"head_sha": "e" * 40}}
                    ),
                },
            )
        )
    assert recorded.primary_success, recorded.error
