# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _complete_case,
    _plan,
    _seed_run,
)

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_resume import (
    prior_deployment_qa_refusals,
)

from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)


def _qa_stage(name: str, plan_id: int, scope: str = "item") -> dict[str, Any]:
    return {
        "name": name,
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
    }


def _stages(plan_id: int) -> list[dict[str, Any]]:
    return [
        {
            "name": "deploy",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        _qa_stage("member-qa-one", plan_id),
        _qa_stage("member-qa-two", plan_id),
        _qa_stage("release-qa", plan_id, "run"),
    ]


def _complete_failed(conn: Any, execution: dict[str, Any]) -> None:
    requirement_id = int(execution["roster"][0]["requirement_id"])
    now = "2026-09-14T00:02:00Z"
    conn.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,started_at,completed_at,created_at"
        ") VALUES (%s,'worktree_run','plan_case','fail',%s,%s,%s)",
        (requirement_id, now, now, now),
    )
    advance_plan_execution(
        conn,
        execution,
        ordinal=0,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "fail",
            "case_outcome": "failed",
        },
    )
    finish_plan_execution(conn, execution, state="completed", reason="test-failed")
