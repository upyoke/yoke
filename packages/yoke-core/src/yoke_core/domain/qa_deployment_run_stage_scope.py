"""Keep a run-wide QA materialization from bypassing a run's scoped stages.

A deployment run's QA stages declare their own scope. An item-scoped stage
counts a member satisfied only through a requirement carrying that stage name
AND that member's item, so a requirement materialized run-wide — no stage, no
member — is invisible to it. Nothing rejected such a write, so the owner of a
member item could run the plan, record a genuine pass, and watch the stage go
on waiting for evidence that structurally could not arrive.

This guard makes that a refusal at the write, naming the stage that will
never count the row and the exact invocation that binds it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.qa_plan_management import QaPlanError

#: The scope a QA stage declares when each run member owes its own evidence.
ITEM_STAGE_SCOPE = "item"


def item_scoped_qa_stages(conn: Any, deployment_run_id: str) -> list[str]:
    """Return the run's pinned QA stages that count per member item."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id=dr.flow "
        f"WHERE dr.id={marker}",
        (str(deployment_run_id),),
    ).fetchone()
    if row is None:
        return []
    raw = row["stages"] if hasattr(row, "keys") else row[0]
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return []
    if not isinstance(stages, list):
        return []
    return [
        str(stage.get("name") or "")
        for stage in stages
        if isinstance(stage, Mapping)
        and stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
        and str(stage.get("scope") or "") == ITEM_STAGE_SCOPE
        and str(stage.get("name") or "")
    ]


def require_stage_scoped_materialization(
    conn: Any,
    *,
    deployment_run_id: str,
    plan: str,
    project: str,
) -> None:
    """Refuse a run-wide write onto a run whose QA stage counts members."""
    stages = item_scoped_qa_stages(conn, deployment_run_id)
    if not stages:
        return
    stage = stages[0]
    raise QaPlanError(
        f"deployment run {deployment_run_id!r} pins item-scoped QA stage "
        f"{stage!r}, which credits a member only through a requirement bound "
        "to that stage and that member. Materializing this plan run-wide "
        "would write requirements the stage never reads, so even a passing "
        "verdict would discharge nothing and the member's wait would re-fire. "
        f"Name the stage and the member: `yoke qa plan run "
        f"--deployment-run-id {deployment_run_id} --stage {stage} "
        f"--member PREFIX-N --plan {plan} --project {project}` (the same "
        "--stage/--member pair works on `yoke qa plan materialize`)."
    )


__all__ = [
    "ITEM_STAGE_SCOPE",
    "item_scoped_qa_stages",
    "require_stage_scoped_materialization",
]
