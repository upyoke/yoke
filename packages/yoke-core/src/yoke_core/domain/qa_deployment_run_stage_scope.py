"""Keep a run-wide QA materialization from bypassing a run's scoped stages.

A deployment run's QA stages count evidence by stage name. Acceptance reads
`deployment_stage = <name>` — and, on an item-scoped stage, the member item
too — so a requirement materialized run-wide, carrying neither, is invisible
to every one of them. Nothing rejected such a write, so an owner could run
the plan, record a genuine pass, and watch the stage go on waiting for
evidence that structurally could not arrive.

That is why the refusal keys on a run pinning *any* QA stage rather than only
an item-scoped one: a run-scoped stage filters on the stage name just the
same, and a NULL-stage row is as invisible to it. The run-wide form survives
only for a run whose flow pins no QA stage at all, where there is no stage to
be invisible to.
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


def pinned_qa_stages(conn: Any, deployment_run_id: str) -> list[dict[str, str]]:
    """Return every QA stage the run's flow pins, with its declared scope."""
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
        {"name": str(stage.get("name") or ""), "scope": str(stage.get("scope") or "")}
        for stage in stages
        if isinstance(stage, Mapping)
        and stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
        and str(stage.get("name") or "")
    ]


def _stage_recipe(
    stage: Mapping[str, str], *, deployment_run_id: str, plan: str, project: str
) -> str:
    """The invocation that binds a plan to one pinned stage."""
    member = (
        " --member PREFIX-N" if stage.get("scope") == ITEM_STAGE_SCOPE else ""
    )
    return (
        f"`yoke qa plan run --deployment-run-id {deployment_run_id} "
        f"--stage {stage['name']}{member} --plan {plan} --project {project}`"
    )


def require_stage_scoped_materialization(
    conn: Any,
    *,
    deployment_run_id: str,
    plan: str,
    project: str,
) -> None:
    """Refuse a run-wide write onto a run whose QA stages count by name."""
    stages = pinned_qa_stages(conn, deployment_run_id)
    if not stages:
        return
    named = ", ".join(
        f"{stage['name']!r} (scope {stage['scope'] or 'unset'!s})" for stage in stages
    )
    recipes = "; ".join(
        _stage_recipe(
            stage,
            deployment_run_id=deployment_run_id,
            plan=plan,
            project=project,
        )
        for stage in stages
    )
    raise QaPlanError(
        f"deployment run {deployment_run_id!r} pins QA stage(s) {named}, each of "
        "which credits only requirements bound to its own stage name (and, on "
        "an item-scoped stage, the member item). Materializing this plan "
        "run-wide would write requirements no stage reads, so even a passing "
        "verdict would discharge nothing and the stage would keep waiting. "
        f"Name the stage this evidence answers for: {recipes} (the same "
        "--stage/--member pair works on `yoke qa plan materialize`)."
    )


__all__ = [
    "ITEM_STAGE_SCOPE",
    "pinned_qa_stages",
    "require_stage_scoped_materialization",
]
