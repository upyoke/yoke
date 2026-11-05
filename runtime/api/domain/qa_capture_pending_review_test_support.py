# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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


def _submit(
    conn: Any, execution: dict, bundle: dict, requirement_id: int, verdict: str
):
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
