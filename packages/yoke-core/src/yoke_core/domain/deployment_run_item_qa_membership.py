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
refused before anything deploys.

Every reader asks the same question and fails closed: composition
validation (``deployment_runs_validation``), the pre-execution check that
reuses it (``handlers.deployment_run_execution``), stage dispatch
(``deployment_qa_stage_dispatch``), the outstanding report
(``deployment_qa_stage_outstanding``), and later stages' prior-acceptance
gate (``deployment_qa_stage_prerequisites``). Creation does not ask the
member question, because it mints an itemless run so ``add-item`` can
attach to it.
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
    "item_qa_no_member_owes_target: the run has no member and its flow owes "
    "no delivery-ready item a delivery, so the item-scoped QA stage passes "
    "with nothing to prove"
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
    """Delivery-ready items this run's flow closes that no other release holds.

    Holding is landing custody, the same answer enrollment uses: a release
    holds an item only when it owes that item's proof and carries its exact
    landing, and a run holding it only for supplemental proof does not count.
    A re-merged landing and an unanswerable one are owed, and so is a
    delivery-ready item whose completion flow cannot be read: that raises,
    so the question fails closed rather than letting a delivering run pass
    memberless.
    """
    from yoke_core.domain.delivery_landing_custody import HELD, landing_custody
    from yoke_core.domain.deployment_item_flow_resolution import (
        FLOW_SOURCE_UNREADABLE,
        item_completion_flow_facts,
    )

    flow, _project, project_id, _stages = _run_facts(conn, run_id)
    terminal = tuple(sorted(ENGINE_TERMINAL_STAGE_IDS))
    rows = query_rows(
        conn,
        "SELECT id FROM items WHERE project_id = %s "
        f"AND status NOT IN ({', '.join('%s' for _ in terminal)}) ORDER BY id",
        (project_id, *terminal),
    )
    facts = item_completion_flow_facts(conn, [int(row[0]) for row in rows])
    unreadable = [
        item_id
        for item_id, fact in facts.items()
        if fact.source == FLOW_SOURCE_UNREADABLE
        and item_requires_release_membership(conn, item_id)
    ]
    if unreadable:
        refs = ", ".join(render_item_ref(conn, item_id) for item_id in unreadable)
        raise ValueError(
            f"the completion flow of delivery-ready {refs} cannot be read "
            "(its project delivery default is unreadable)"
        )
    candidates = [
        item_id
        for item_id, fact in facts.items()
        if flow in fact.closing_flows
        and item_requires_release_membership(conn, item_id)
    ]
    custody = landing_custody(
        conn, project_id=project_id, item_ids=candidates, exclude_run_id=run_id
    )
    return tuple(item_id for item_id in candidates if custody[item_id].state != HELD)


def memberless_item_qa_refusal(conn: Any, run_id: str) -> str:
    """Why a memberless item-scoped QA stage may not pass, or ``''``.

    Asked again wherever the stage is judged, rather than trusting the check
    before execution: a run that turns out to owe a delivery, or whose
    custody cannot be read, fails closed instead of passing with nothing.
    """
    owed, unreadable = _owed_or_unreadable(conn, run_id)
    return unreadable or (_owed_refusal(conn, run_id, owed) if owed else "")


def _owed_or_unreadable(conn: Any, run_id: str) -> tuple[tuple[int, ...], str]:
    try:
        return owed_delivery_item_ids(conn, run_id), ""
    except (LookupError, ValueError) as exc:
        return (), (
            f"item_qa_owed_delivery_unreadable: run '{run_id}' has no member and "
            f"whether its flow owes a delivery could not be read: {exc}. "
            "Recovery: repair the named read, then validate or resume again."
        )


def _owed_refusal(conn: Any, run_id: str, owed: tuple[int, ...]) -> str:
    flow, _project, _project_id, stages = _run_facts(conn, run_id)
    refs = ", ".join(render_item_ref(conn, item_id) for item_id in owed)
    return (
        f"item_qa_run_without_members: run '{run_id}' is on the completion flow "
        f"'{flow}' for delivery-ready {refs}, which no other release holds, "
        "but it enrolled none of them, so it would deploy and deliver nobody "
        f"before its item-scoped QA stage(s) {', '.join(stages)} failed. "
        "Their merges are not in this run's release lineage, or composition "
        "skipped them for a reason it names. Recovery: create the run from a "
        "release lineage that contains their merges, or attach one with "
        f"`yoke deployment-runs add-item {run_id} PREFIX-N`, then validate again."
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
    owed, unreadable = _owed_or_unreadable(conn, run_id)
    if unreadable:
        # Creation leaves the member question to the checks after it.
        return (unreadable if require_members else ""), ""
    if not owed:
        return "", f"{', '.join(stages)}: {NO_MEMBER_OWES_TARGET}"
    if not custody:
        return _custody_refusal(flow, project, stages), ""
    if not require_members:
        return "", ""
    return _owed_refusal(conn, run_id, owed), ""


def require_item_qa_membership_possible(conn: Any, run_id: str) -> None:
    """Refuse an attach the run's item-scoped QA stage could never prove."""
    flow, project, _project_id, stages = _run_facts(conn, run_id)
    if stages and not requires_release_admission(conn, run_id):
        raise ValueError(_custody_refusal(flow, project, stages))


__all__ = [
    "NO_MEMBER_OWES_TARGET",
    "item_qa_membership_verdict",
    "memberless_item_qa_refusal",
    "owed_delivery_item_ids",
    "require_item_qa_membership_possible",
]
