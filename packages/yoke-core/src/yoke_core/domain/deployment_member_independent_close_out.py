"""Recognize a final member delivered before its sibling QA completes.

Only a selected flow with no shared QA or human approval, whose last
substantive stage is item QA, can discharge one member while its run remains
executing. Trailing no-op auto stages carry no further delivery obligation.
The QA acceptance reader verifies the current deployment receipt, candidate,
cases, and verdict for that member.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
    pinned_stages,
)
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run


def independent_member_delivery_ready(conn: Any, *, item_id: int, run_id: str) -> bool:
    """True only after this member's final production QA is accepted.

    A run-level QA or human-approval stage is shared, wherever it appears in
    the flow. Either keeps every final member open until the run succeeds. A
    failed or cancelled run never qualifies. The selected-flow membership and
    frozen final intent are required even if another run carries the item.
    """
    from yoke_core.domain.deployment_run_composition_freeze import DELIVERY_INTENT_FINAL

    run = latest_completion_run(conn, int(item_id))
    if run is None or run["id"] != str(run_id) or run["status"] != "executing":
        return False
    row = conn.execute(
        "SELECT dri.delivery_intent,e.name AS target_name "
        "FROM deployment_run_items dri "
        "JOIN deployment_runs dr ON dr.id=dri.run_id "
        "LEFT JOIN environments e ON e.id=dr.target_environment_id "
        "WHERE dri.run_id=%s AND dri.item_id=%s",
        (str(run_id), int(item_id)),
    ).fetchone()
    if row is None or str(row["delivery_intent"] or "") != DELIVERY_INTENT_FINAL:
        return False
    target_name = str(row["target_name"] or "")
    if not target_name:
        return False
    stages = pinned_stages(conn, str(run_id))
    qa_stages = [
        stage
        for stage in stages
        if stage.get("stage_kind") == "qa" or stage.get("step_runner") == "qa"
    ]
    if (
        not qa_stages
        or any(stage.get("scope") == "run" for stage in qa_stages)
        or any(stage.get("step_runner") == "human-approval" for stage in stages)
    ):
        return False
    final_stage = qa_stages[-1]
    target = final_stage.get("target") or {}
    trailing = stages[stages.index(final_stage) + 1 :]
    if (
        any(
            stage.get("step_runner") != "auto" or stage.get("stage_kind") != "execution"
            for stage in trailing
        )
        or final_stage.get("scope") != "item"
        or not isinstance(target, dict)
        or target.get("kind") != "persistent_environment"
        or target.get("environment") != target_name
    ):
        return False
    return not item_qa_acceptance_blockers(
        conn, run_id=str(run_id), item_id=int(item_id)
    )


__all__ = ["independent_member_delivery_ready"]
