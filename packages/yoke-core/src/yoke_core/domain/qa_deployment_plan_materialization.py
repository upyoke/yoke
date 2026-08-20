"""Deployment-run QA plan snapshot materialization."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_one, query_rows
from yoke_core.domain.qa_plan_management import QaPlanError, _placeholder
from yoke_core.domain.qa_execution_environment_target import (
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_requirement_snapshot import (
    require_existing_target,
    require_requirement_id_target,
)


def materialize_deployment_plan(
    conn: Any,
    *,
    deployment_run_id: str,
    plan: str,
    project: Optional[str] = None,
    commit: bool = True,
    insert_requirement_fn: Callable[..., int | None],
    existing_requirement_id_fn: Callable[..., int | None],
) -> dict:
    """Snapshot one named project plan onto a real deployment run."""
    marker = _placeholder(conn)
    run = query_one(
        conn,
        "SELECT dr.project_id, p.slug AS project "
        "FROM deployment_runs dr JOIN projects p ON p.id=dr.project_id "
        f"WHERE dr.id={marker}",
        (str(deployment_run_id),),
    )
    if run is None:
        raise QaPlanError(f"deployment run {deployment_run_id!r} not found")
    if project is not None and str(run["project"]) != str(project):
        raise QaPlanError("deployment run does not belong to the requested project")
    plan_row = query_one(
        conn,
        "SELECT * FROM qa_plans "
        f"WHERE project_id={marker} AND "
        f"(slug={marker} OR CAST(id AS TEXT)={marker}) "
        "AND retired_at IS NULL",
        (int(run["project_id"]), str(plan), str(plan)),
    )
    if plan_row is None:
        raise QaPlanError(f"QA plan {plan!r} not found in project {run['project']!r}")
    plan_id = int(plan_row["id"])
    execution_target = resolve_plan_execution_target(conn, plan_id=plan_id)
    cases = query_rows(
        conn,
        "SELECT c.*, m.name AS method_name, m.runner_id, "
        "m.required_capability_kinds, m.verdict_path, m.config_contract_id "
        "FROM qa_plan_cases c JOIN qa_methods m ON m.id=c.method_id "
        f"WHERE c.plan_id={marker} ORDER BY c.position",
        (plan_id,),
    )
    if not cases:
        raise QaPlanError(f"QA plan {plan_id} has no cases and cannot be materialized")
    existing_rows = query_rows(
        conn,
        "SELECT id,execution_target_json,execution_target_digest "
        "FROM qa_requirements "
        f"WHERE deployment_run_id={marker} AND plan_id={marker} "
        "ORDER BY id",
        (str(deployment_run_id), plan_id),
    )
    if existing_rows:
        # The first committed row freezes the whole deployment-run snapshot,
        # matching item materialization. The write below commits only after
        # every expanded case is inserted; failures roll the transaction back,
        # and the deployment materialization unique index converges races.
        return {
            "deployment_run_id": str(deployment_run_id),
            "project": str(run["project"]),
            "plan_id": plan_id,
            "created_requirement_ids": [],
            "existing_requirement_ids": require_existing_target(
                existing_rows,
                execution_target=execution_target,
                subject=f"deployment run {deployment_run_id!r}",
            ),
        }

    created: list[int] = []
    existing: list[int] = []
    attachment = {"qa_phase": "post_deploy"}
    now = iso8601_now()
    try:
        for case in cases:
            baselines = json.loads(str(case["host_baselines"] or "[]")) or [None]
            for baseline_position, baseline in enumerate(baselines, start=1):
                requirement_id = insert_requirement_fn(
                    conn,
                    deployment_run_id=str(deployment_run_id),
                    plan=plan_row,
                    attachment=attachment,
                    case=case,
                    baseline=baseline,
                    baseline_position=baseline_position,
                    now=now,
                    execution_target=execution_target,
                )
                if requirement_id is not None:
                    created.append(requirement_id)
                    continue
                requirement_id = existing_requirement_id_fn(
                    conn,
                    deployment_run_id=str(deployment_run_id),
                    plan_id=plan_id,
                    case_key=str(case["case_key"]),
                    baseline=baseline,
                )
                if requirement_id is not None:
                    existing.append(
                        require_requirement_id_target(
                            conn,
                            requirement_id=requirement_id,
                            execution_target=execution_target,
                            subject=f"deployment run {deployment_run_id!r}",
                        )
                    )
        if commit:
            conn.commit()
    except Exception:
        if commit:
            conn.rollback()
        raise
    return {
        "deployment_run_id": str(deployment_run_id),
        "project": str(run["project"]),
        "plan_id": plan_id,
        "created_requirement_ids": created,
        "existing_requirement_ids": existing,
    }


__all__ = ["materialize_deployment_plan"]
