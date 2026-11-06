# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _seed_run,
    _stages,
)

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)

from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

from yoke_core.domain.qa_requirement_pass_currency import stamp_executed_method_config


def _ids(execution: dict[str, Any]) -> list[int]:
    return [int(row["requirement_id"]) for row in execution["roster"]]


def _pass(
    conn: Any,
    execution: dict[str, Any],
    ordinal: int,
    digest: str | None = None,
    *,
    evidence: bool = True,
) -> int:
    requirement_id = _ids(execution)[ordinal]
    config = conn.execute(
        "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()[0]
    raw = stamp_executed_method_config(
        "case passed",
        config,
        execution_target_digest=digest,
        conn=conn,
        requirement_id=requirement_id,
    )
    now = f"2026-09-14T00:0{2 + ordinal}:00Z"
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) VALUES "
        "(%s,'worktree_run','plan_case','pass',%s,%s,%s,%s) RETURNING id",
        (requirement_id, raw, now, now, now),
    ).fetchone()[0]
    if evidence:
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
            (run_id, f"evidence://case-{requirement_id}", now),
        )
    advance_plan_execution(
        conn,
        execution,
        ordinal=ordinal,
        requirement_id=requirement_id,
        result={
            "requirement_id": requirement_id,
            "verdict": "pass",
            "case_outcome": "passed",
            "run_id": int(run_id),
        },
    )
    return requirement_id
