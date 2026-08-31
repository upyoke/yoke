"""Dispatch every gate family whose evaluator lives outside the composer.

The composer owns the gates it evaluates inline; everything else — the
activation operations the delivery workflows list, the direct-workflow
closure gates, and the approval gate — resolves to a registered
evaluator here. One table, so a gate id a definition may carry always
has somewhere to land and a listed gate can never quietly do nothing.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import workflow_activation_status_gates
from yoke_core.domain.workflow_gate_catalog import (
    GATE_APPROVAL,
    GATE_CONFLICT_SURVEY,
    GATE_DASH_EVIDENCE,
    GATE_DOC_CLAIM_ACTIVATION,
    GATE_DOC_COMPLETION,
    GATE_FLOOR_ATTESTATION,
    GATE_WORK_CLAIM_ACTIVATION,
)

_GATE_IDS = frozenset(
    {
        GATE_APPROVAL,
        GATE_CONFLICT_SURVEY,
        GATE_DASH_EVIDENCE,
        GATE_DOC_CLAIM_ACTIVATION,
        GATE_DOC_COMPLETION,
        GATE_FLOOR_ATTESTATION,
        GATE_WORK_CLAIM_ACTIVATION,
    }
)


def handles(gate_id: str) -> bool:
    return gate_id in _GATE_IDS or workflow_activation_status_gates.handles(
        gate_id
    )


def evaluate(
    *,
    gate_id: str,
    item_id: int,
    target_status: str,
    db_path: str,
    session_id: Optional[str],
    conn: Optional[Any] = None,
) -> Optional[dict]:
    """Run one known family; callers must check :func:`handles` first."""
    if workflow_activation_status_gates.handles(gate_id):
        return workflow_activation_status_gates.evaluate(
            gate_id=gate_id,
            item_id=item_id,
            target_status=target_status,
            db_path=db_path,
            session_id=session_id,
            conn=conn,
        )
    if gate_id == GATE_CONFLICT_SURVEY:
        from yoke_core.domain.conflict_survey_gate import evaluate as evaluator
    elif gate_id == GATE_DOC_COMPLETION:
        from yoke_core.domain.doc_completion_gate import evaluate as evaluator
    elif gate_id == GATE_DASH_EVIDENCE:
        from yoke_core.domain.dash_evidence_gate import evaluate as evaluator
    elif gate_id == GATE_FLOOR_ATTESTATION:
        from yoke_core.domain.floor_attestation_gate import evaluate as evaluator
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
            conn=conn,
        )
    return evaluator(
        item_id=item_id,
        target_status=target_status,
        db_path=db_path,
    )


__all__ = ["evaluate", "handles"]
