"""Delivery gates every pinned definition carries by its own structure.

None of these is listed on a stage. Each is derived from the definition's
shape — which stage takes the lane, which stages its delivery policy
treats as merged — so it holds for a plain
``lifecycle.transition`` on every workflow, not only for the skill that
used to check it by hand.

* Dependency edges by stage range: activation edges hold at every working
  stage from the lane-taking stage until the merge boundary; integration
  edges hold at every stage that implies a merge.
* Merge record: a non-terminal stage that implies a merge (the release wait)
  requires the landing to be recorded, unless the item's own execution
  evidence attests a no-change result that never had anything to land.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.dependency_types import GatePoint
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.workflow_gate_catalog import (
    GATE_CHECK_HARD_BLOCKS,
    activation_operation_gate_ids,
)


def activation_stage_index(workflow: Any) -> Optional[int]:
    """Position of the first stage that takes a lane, or ``None``."""
    activation_ids = activation_operation_gate_ids()
    for position, stage_id in enumerate(workflow.stage_ids):
        if workflow.gate_ids_for_stage(stage_id) & activation_ids:
            return position
    return None


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def evaluate_dependency_edges(
    *,
    conn: Any,
    item_id: int,
    target_status: str,
    workflow: Any,
    db_path: str,
    **_: Any,
) -> Optional[dict]:
    """Activation edges guard the work; integration edges guard the landing."""
    from yoke_core.domain.workflow_activation_status_gates import (
        evaluate_check_hard_blocks,
    )

    position = workflow.stage_index(target_status)
    if workflow.stage_implies_merge(target_status):
        gate_point = GatePoint.INTEGRATION.value
    else:
        activation = activation_stage_index(workflow)
        if activation is None or position < activation:
            return None
        if GATE_CHECK_HARD_BLOCKS in workflow.gate_ids_for_stage(target_status):
            return None  # the listed gate already evaluates activation here
        gate_point = GatePoint.ACTIVATION.value
    return evaluate_check_hard_blocks(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
        conn=conn,
        gate_point=gate_point,
    )


def _attests_no_change(conn: Any, item_id: int) -> bool:
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION
    from yoke_core.domain.item_json_sections import read_json_section

    evidence = read_json_section(
        conn, item_id=int(item_id), section=DASH_EVIDENCE_SECTION
    )
    return isinstance(evidence, dict) and evidence.get("no_changes") is True


def evaluate_merge_record(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """The release wait is entered only by a recorded landing."""
    if target_status in workflow.terminal_stage_ids:
        return None  # the done ceremony owns terminal merge verification
    if not workflow.stage_implies_merge(target_status):
        return None
    row = conn.execute(
        f"SELECT merged_at FROM items WHERE id = {_p(conn)}", (int(item_id),)
    ).fetchone()
    merged_at = (row["merged_at"] if hasattr(row, "keys") else row[0]) if row else None
    if merged_at not in (None, "", "null"):
        return None
    if _attests_no_change(conn, item_id):
        return None
    ref = render_item_ref(conn, int(item_id))
    return {
        "success": False,
        "error_code": "GATE_MERGE_UNRECORDED",
        "error": (
            f"Cannot advance {ref} to {target_status!r} — the pinned "
            "definition treats this stage as merged, and no landing is "
            "recorded (items.merged_at is empty and the execution evidence "
            "attests no no-change result)."
        ),
        "remediation_hint": (
            f"Land the branch with `yoke merge item {ref}`, which records the "
            "landing and walks the declared stages; a genuine no-change result "
            "records `--no-changes` evidence instead."
        ),
    }


__all__ = [
    "activation_stage_index",
    "evaluate_dependency_edges",
    "evaluate_merge_record",
]
