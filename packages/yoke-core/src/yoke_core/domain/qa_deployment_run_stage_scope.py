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

Plan materialization is not the only way such a row is born, so the same
boundary is offered per requirement in
:func:`require_stage_scoped_requirement`. A blocking run-bound obligation
naming no stage holds the run's completion while no stage can ever credit
it, whichever surface authored it — which is how a run ends up with every
stage delivered and a status that will not settle.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.schema_common import _table_exists

#: The scope a QA stage declares when each run member owes its own evidence.
ITEM_STAGE_SCOPE = "item"


def pinned_qa_stages(conn: Any, deployment_run_id: str) -> list[dict[str, str]]:
    """Return every QA stage the run's flow pins, with its declared scope.

    A universe carrying no deployment tables pins no stage, so it reports
    an empty list rather than failing: the QA fixtures that exercise
    requirement authoring create only the QA tables they use, and a run
    that cannot exist has no stage to be invisible to.
    """
    if not (
        _table_exists(conn, "deployment_runs")
        and _table_exists(conn, "deployment_flows")
    ):
        return []
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


def require_stage_scoped_requirement(
    conn: Any,
    *,
    deployment_run_id: str,
    blocking_mode: str | None,
    deployment_stage: str | None,
) -> None:
    """Refuse a stage-less blocking obligation a staged run cannot credit.

    Only a blocking one is refused. A non-blocking row is equally invisible
    to stage acceptance but holds nothing, so rejecting it would cost an
    author a note the run was never going to wait on.
    """
    if deployment_stage or str(blocking_mode or "blocking") != "blocking":
        return
    stages = pinned_qa_stages(conn, deployment_run_id)
    if not stages:
        return
    named = ", ".join(
        f"{stage['name']!r} (scope {stage['scope'] or 'unset'!s})"
        for stage in stages
    )
    raise QaPlanError(
        f"deployment run {deployment_run_id!r} pins QA stage(s) {named}, and a "
        "blocking obligation naming no stage is credited by none of them. It "
        "would hold the run's completion — and its final stage — for evidence "
        "that structurally cannot arrive. Name the stage this obligation "
        "belongs to (`deployment_stage`, plus the member item on an "
        "item-scoped stage), or record it as non-blocking if nothing should "
        "wait on it."
    )


__all__ = [
    "ITEM_STAGE_SCOPE",
    "pinned_qa_stages",
    "require_stage_scoped_materialization",
    "require_stage_scoped_requirement",
]
