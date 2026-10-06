"""Refuse a run whose item-scoped QA stage could never be passed.

An item-scoped QA stage proves each member against the requirement snapshot
frozen for it, and the freeze only runs on a flow that takes delivery
custody. So two compositions are dead on arrival: a flow without custody,
whose members never receive a snapshot, and a run that enrolls no member at
all, which leaves the stage nothing to prove. Both used to be accepted and
then fail at the QA stage after the whole deploy had already run; asking
here moves that answer to before the run is minted or started.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.deployment_flow_policy import STAGE_KIND_QA
from yoke_core.domain.deployment_run_composition_freeze import (
    requires_release_admission,
)
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain.json_helper import loads_text


def _item_qa_stage_names(conn: Any, run_id: str) -> tuple[str, str, tuple[str, ...]]:
    """The run's flow id, project slug, and its item-scoped QA stage names."""
    rows = query_rows(
        conn,
        "SELECT dr.flow, p.slug, df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id = dr.flow "
        "JOIN projects p ON p.id = dr.project_id WHERE dr.id = %s",
        (run_id,),
    )
    if not rows:
        raise LookupError(f"deployment run '{run_id}' not found")
    flow, project, raw_stages = rows[0][0], rows[0][1], rows[0][2]
    stages = loads_text(raw_stages) if raw_stages else []
    names = tuple(
        str(stage.get("name") or "")
        for stage in stages
        if isinstance(stage, dict)
        and stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("scope") == "item"
    )
    return str(flow), str(project), names


def _custody_refusal(flow: str, project: str, stages: tuple[str, ...]) -> str:
    return (
        f"item_qa_flow_without_delivery_custody: flow '{flow}' has item-scoped "
        f"QA stage(s) {', '.join(stages)} but does not take delivery custody, "
        "so no member ever receives the frozen requirement snapshot those "
        "stages prove against. Recovery: run on a flow whose "
        f"takes_delivery_custody is true (`yoke deployment-flows list "
        f"--project {project}`), or give flow '{flow}' delivery custody or "
        "drop its item-scoped QA stages in a new flow version."
    )


def item_qa_membership_refusal(
    conn: Any, run_id: str, *, require_members: bool = True
) -> str:
    """Name why this run's item-scoped QA could never pass, or ``''``.

    Read after enrollment, so the member count is the one the run executes.
    A run whose members were all deliberately removed still reaches its
    stage, which accounts for removals itself; only a run that never had a
    member is refused. Creation passes ``require_members=False``: an itemless
    run is minted so ``add-item`` can attach to it, and the member count is
    answered by the validation that precedes execution instead.
    """
    flow, project, stages = _item_qa_stage_names(conn, run_id)
    if not stages:
        return ""
    if not requires_release_admission(conn, run_id):
        return _custody_refusal(flow, project, stages)
    if not require_members:
        return ""
    members = query_scalar(
        conn,
        "SELECT COUNT(*) FROM deployment_run_items WHERE run_id = %s",
        (run_id,),
    )
    if int(members or 0) or removed_item_ids(conn, run_id):
        return ""
    return (
        f"item_qa_run_without_members: flow '{flow}' has item-scoped QA "
        f"stage(s) {', '.join(stages)}, but run '{run_id}' enrolls no member: "
        "no delivery-ready item is carried by its release lineage, so the "
        "deploy would run and then fail at item QA with nothing to prove. "
        "Recovery: attach a delivery-ready member with `yoke deployment-runs "
        "add-item`, or land delivery-ready work into the release lineage and "
        "validate again (held candidates are listed below), or use a flow "
        "without an item-scoped QA stage."
    )


def require_item_qa_membership_possible(conn: Any, run_id: str) -> None:
    """Refuse an attach the run's item-scoped QA stage could never prove."""
    flow, project, stages = _item_qa_stage_names(conn, run_id)
    if stages and not requires_release_admission(conn, run_id):
        raise ValueError(_custody_refusal(flow, project, stages))


__all__ = [
    "item_qa_membership_refusal",
    "require_item_qa_membership_possible",
]
