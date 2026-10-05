"""Compose the status-write gates a pinned definition does not list.

Listed stage gates are the definition's explicit placements. These are the
rest. Terminal QA settlement, closure dependencies, and the Dash posture
knobs run first and are never bypassed. Then come the structural gates:
obligations that follow from the definition's shape — its lane-taking
stage, its merge boundary, its implementation binding, its delivery and
generated-children policies — and so hold for a plain
``lifecycle.transition`` on every workflow version, whichever caller moves
the item. A refusal names its reason and the recovery.

Order is cheapest and most fundamental first. Task-graph existence and
File Budget coverage are never bypassed; ``force`` skips the rest, matching
how it treats the listed gates it may skip.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from yoke_core.domain import qa_attached_transition_gate
from yoke_core.domain import db_helpers
from yoke_core.domain.workflow_delivery_status_gates import (
    activation_stage_index,
    evaluate_delivery_flow,
    evaluate_dependency_edges,
    evaluate_merge_record,
)
from yoke_core.domain.workflow_task_graph_status_gates import (
    evaluate_deferred_items,
    evaluate_shepherd_verdict,
    evaluate_task_completion,
    evaluate_task_existence,
)


def evaluate_spec_coverage(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """Working stages hold the File Budget inside the item's path claims.

    Applies only when the effective File Budget and path-claim policies are
    both on (the coverage evaluator answers that itself); a task-graph
    parent's per-task coverage belongs to its planning handoff.
    """
    from yoke_core.domain import path_claim_spec_coverage_gate
    from yoke_core.domain.workflow_behavior import generates_task_graph

    if generates_task_graph(workflow) or target_status in workflow.terminal_stage_ids:
        return None
    activation = activation_stage_index(workflow)
    position = workflow.stage_index(target_status)
    if activation is None or position < activation:
        return None
    result = path_claim_spec_coverage_gate.evaluate(int(item_id), conn=conn)
    if not result.is_blocked:
        return None
    missing = ", ".join(result.missing_paths)
    return {
        "success": False,
        "error_code": "GATE_SPEC_COVERAGE",
        "error": (
            f"Cannot advance {result.public_ref} to {target_status!r} — its "
            f"File Budget lists {len(result.missing_paths)} path(s) no active "
            f"path claim covers: {missing}."
        ),
        "remediation_hint": (
            "Widen the claim with `yoke claims path widen --claim-id <id> "
            f'--add-paths {missing} --reason "<why>" --item '
            f"{result.public_ref}`, or repair the File Budget through "
            "`/yoke refine` before the item takes its lane."
        ),
    }


Evaluator = Callable[..., Optional[dict]]

_NEVER_BYPASSED: tuple[Evaluator, ...] = (
    evaluate_task_existence,
    evaluate_spec_coverage,
)
_FORCE_BYPASSABLE: tuple[Evaluator, ...] = (
    evaluate_dependency_edges,
    evaluate_delivery_flow,
    evaluate_shepherd_verdict,
    evaluate_task_completion,
    evaluate_deferred_items,
    evaluate_merge_record,
    qa_attached_transition_gate.evaluate,
)


def evaluate(
    *,
    conn: Any,
    item_id: int,
    target_status: str,
    workflow: Any,
    force: bool,
    db_path: str,
) -> Optional[dict]:
    """Return the first structural refusal, or ``None`` when all hold."""
    if workflow.stage_index(target_status) is None:
        return None  # exceptional stages carry no structural obligation
    evaluators = _NEVER_BYPASSED if force else _NEVER_BYPASSED + _FORCE_BYPASSABLE
    for evaluator in evaluators:
        failure = evaluator(
            conn=conn,
            item_id=item_id,
            target_status=target_status,
            workflow=workflow,
            db_path=db_path,
        )
        if failure is not None:
            return failure
    return None


def evaluate_unlisted(
    *,
    item_id: int,
    target_status: str,
    workflow: Any,
    force: bool,
    db_path: str,
    conn: Optional[Any],
) -> Optional[dict]:
    """Every unlisted gate, on the transition's own connection."""
    from yoke_core.domain.closure_status_gate import evaluate_for_status_write
    from yoke_core.domain.qa_terminal_settlement import terminal_transition_result

    terminal = terminal_transition_result(conn, item_id, target_status, workflow)
    if terminal:
        return terminal
    closure = evaluate_for_status_write(
        item_id=item_id, target_status=target_status, db_path=db_path, conn=conn
    )
    if closure is not None:
        return closure
    if workflow.workflow_id == "dash":
        from yoke_core.domain.dash_posture_gate import evaluate as evaluate_posture

        posture = evaluate_posture(
            item_id=item_id, target_status=target_status, db_path=db_path
        )
        if posture is not None:
            return posture
    gate_conn = conn if conn is not None else db_helpers.connect(db_path)
    try:
        return evaluate(
            conn=gate_conn,
            item_id=item_id,
            target_status=target_status,
            workflow=workflow,
            force=force,
            db_path=db_path,
        )
    finally:
        if conn is None:
            gate_conn.close()


__all__ = ["evaluate", "evaluate_spec_coverage", "evaluate_unlisted"]
