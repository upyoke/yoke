"""Dispatch the direct-workflow and approval gate families."""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.workflow_gate_catalog import (
    GATE_APPROVAL,
    GATE_CONFLICT_SURVEY,
    GATE_DASH_EVIDENCE,
    GATE_DOC_CLAIM_ACTIVATION,
    GATE_DOC_COMPLETION,
    GATE_WORK_CLAIM_ACTIVATION,
)

_GATE_IDS = frozenset(
    {
        GATE_APPROVAL,
        GATE_CONFLICT_SURVEY,
        GATE_DASH_EVIDENCE,
        GATE_DOC_CLAIM_ACTIVATION,
        GATE_DOC_COMPLETION,
        GATE_WORK_CLAIM_ACTIVATION,
    }
)


def handles(gate_id: str) -> bool:
    return gate_id in _GATE_IDS


def evaluate(
    *,
    gate_id: str,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str],
) -> Optional[dict]:
    """Run one known family; callers must check :func:`handles` first."""
    if gate_id == GATE_CONFLICT_SURVEY:
        from yoke_core.domain.conflict_survey_gate import evaluate as evaluator
    elif gate_id == GATE_DOC_COMPLETION:
        from yoke_core.domain.doc_completion_gate import evaluate as evaluator
    elif gate_id == GATE_DASH_EVIDENCE:
        from yoke_core.domain.dash_evidence_gate import evaluate as evaluator
    elif gate_id == GATE_APPROVAL:
        from yoke_core.domain.approval_status_gate import evaluate as evaluator
    else:
        from yoke_core.domain import direct_workflow_activation_gate

        evaluator = (
            direct_workflow_activation_gate.evaluate_work_claim_activation
            if gate_id == GATE_WORK_CLAIM_ACTIVATION
            else direct_workflow_activation_gate.evaluate_doc_claim_activation
        )
        return evaluator(
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            session_id=session_id,
        )
    return evaluator(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )


__all__ = ["evaluate", "handles"]
