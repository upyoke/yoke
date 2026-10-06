"""Decide whether a run's item-scoped QA stage can do its job.

An item-scoped QA stage proves each member against the requirement snapshot
the composition freeze writes, and only a flow that takes delivery custody
freezes one. So a member on a custody-free flow can never be proven.

A run with no member is a different question: whether it owes anyone a
delivery. A stage run in a stage-and-production pair legitimately carries
no member when no item owes QA at its target — targeting leaves it empty on
purpose — and its item-scoped stage passes with nothing to prove. A run that
is the completion flow for delivery-ready items no other release holds,
yet enrolled none of them, would deploy and then deliver nobody; that one is
refused before anything deploys. The refusal is asked at validation and
again before execution rather than at creation, because creation mints an
itemless run so ``add-item`` can attach to it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_rows, query_scalar
from yoke_core.domain.deployment_flow_policy import STAGE_KIND_QA
from yoke_core.domain.deployment_run_composition_freeze import (
    item_requires_release_membership,
    requires_release_admission,
)
from yoke_core.domain.deployment_run_membership_removals import removed_item_ids
from yoke_core.domain.json_helper import loads_text
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS

#: The named result an item-scoped QA stage reports when no member owes it.
NO_MEMBER_OWES_TARGET = (
    "item_qa_no_member_owes_target: no item this run carries owes QA at its "
    "target, so the item-scoped QA stage passes with nothing to prove"
)


def _run_facts(conn: Any, run_id: str) -> tuple[str, str, int, tuple[str, ...]]:
    """The run's flow, project slug and id, and its item-scoped QA stages."""
    rows = query_rows(
        conn,
        "SELECT dr.flow, p.slug, dr.project_id, df.stages FROM deployment_runs dr "
        "JOIN deployment_flows df ON df.id = dr.flow "
        "JOIN projects p ON p.id = dr.project_id WHERE dr.id = %s",
        (run_id,),
    )
    if not rows:
        raise LookupError(f"deployment run '{run_id}' not found")
    flow, project, project_id, raw_stages = rows[0][:4]
    stages = loads_text(raw_stages) if raw_stages else []
    names = tuple(
        str(stage.get("name") or "")
        for stage in stages
        if isinstance(stage, dict)
        and stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("scope") == "item"
    )
    return str(flow), str(project), int(project_id), names


def owed_delivery_item_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    """Delivery-ready items this run's flow closes that no other release holds."""
    from yoke_core.domain.deployment_item_flow_resolution import (
        item_completion_flows,
    )

    flow, _project, project_id, _stages = _run_facts(conn, run_id)
    terminal = tuple(sorted(ENGINE_TERMINAL_STAGE_IDS | {"done"}))
    rows = query_rows(
        conn,
        "SELECT i.id FROM items i WHERE i.project_id = %s "
        f"AND i.status NOT IN ({', '.join('%s' for _ in terminal)}) "
        "AND NOT EXISTS (SELECT 1 FROM deployment_run_items dri "
        "JOIN deployment_runs dr ON dr.id = dri.run_id WHERE dri.item_id = i.id "
        "AND dr.id <> %s AND dr.status NOT IN ('failed', 'cancelled')) "
        "ORDER BY i.id",
        (project_id, *terminal, run_id),
    )
    flows = item_completion_flows(conn, [int(row[0]) for row in rows])
    return tuple(
        item_id
        for item_id, completion_flow in flows.items()
        if completion_flow == flow and item_requires_release_membership(conn, item_id)
    )


def _custody_refusal(flow: str, project: str, stages: tuple[str, ...]) -> str:
    return (
        f"item_qa_flow_without_delivery_custody: flow '{flow}' has item-scoped "
        f"QA stage(s) {', '.join(stages)} but does not take delivery custody, "
        "so no member ever receives the frozen requirement snapshot those "
        "stages prove against. Recovery: run on a flow whose "
        f"takes_delivery_custody is true (`yoke deployment-flows list "
        f"--project {project}`), or give flow '{flow}' delivery custody in a "
        "new flow version."
    )


def item_qa_membership_verdict(
    conn: Any, run_id: str, *, require_members: bool = True
) -> tuple[str, str]:
    """``(refusal, notice)`` for this run's item-scoped QA; each may be ``''``.

    Read after enrollment, so the member count is the one the run executes.
    A run whose members were all deliberately removed still reaches its
    stage, which accounts for removals itself. Creation passes
    ``require_members=False`` so an itemless run can be minted for
    ``add-item``; validation and the pre-execution check ask the full question.
    """
    flow, project, _project_id, stages = _run_facts(conn, run_id)
    if not stages:
        return "", ""
    custody = requires_release_admission(conn, run_id)
    members = query_scalar(
        conn, "SELECT COUNT(*) FROM deployment_run_items WHERE run_id = %s", (run_id,)
    )
    if int(members or 0) or removed_item_ids(conn, run_id):
        return ("" if custody else _custody_refusal(flow, project, stages)), ""
    owed = owed_delivery_item_ids(conn, run_id)
    if not owed:
        return "", f"{', '.join(stages)}: {NO_MEMBER_OWES_TARGET}"
    if not custody:
        return _custody_refusal(flow, project, stages), ""
    if not require_members:
        return "", ""
    refs = ", ".join(render_item_ref(conn, item_id) for item_id in owed)
    return (
        f"item_qa_run_without_members: run '{run_id}' is the completion flow "
        f"'{flow}' for delivery-ready {refs}, which no other release holds, "
        "but it enrolled none of them, so it would deploy and deliver nobody "
        f"before its item-scoped QA stage(s) {', '.join(stages)} failed. "
        "Their merges are not in this run's release lineage, or composition "
        "skipped them for a reason it names. Recovery: create the run from a "
        "release lineage that contains their merges, or attach one with "
        "`yoke deployment-runs add-item RUN-ID PREFIX-N`, then validate again."
    ), ""


def require_item_qa_membership_possible(conn: Any, run_id: str) -> None:
    """Refuse an attach the run's item-scoped QA stage could never prove."""
    flow, project, _project_id, stages = _run_facts(conn, run_id)
    if stages and not requires_release_admission(conn, run_id):
        raise ValueError(_custody_refusal(flow, project, stages))


__all__ = [
    "NO_MEMBER_OWES_TARGET",
    "item_qa_membership_verdict",
    "owed_delivery_item_ids",
    "require_item_qa_membership_possible",
]
