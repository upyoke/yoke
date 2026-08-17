"""Phase-anchored QA migration compatibility for unlinked requirements."""

from __future__ import annotations

from yoke_core.domain.qa_workflow_binding_validation import (
    QaWorkflowBindingError,
    qa_enforcement_signature,
    transition_for_gate,
)
from yoke_core.domain.workflow_gate_catalog import GATE_QA_VERIFICATION
from yoke_core.domain.workflow_item_migration_common import mapped_stage
from yoke_core.domain.workflow_runtime import WorkflowRuntime


def _qa_anchor_stage(workflow: WorkflowRuntime) -> str | None:
    try:
        return transition_for_gate(workflow, GATE_QA_VERIFICATION)
    except QaWorkflowBindingError:
        return None


def phase_anchored_qa_conflict(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    *,
    binding: str,
) -> str | None:
    """Explain why an unlinked QA requirement cannot survive the migration.

    Requirements that predate stage linkage carry no
    ``workflow_transition_id``. Runtime QA gates never read that column —
    they enforce by phase at whichever stage carries the
    ``qa_verification`` gate — so compatibility compares the enforcement
    reachable from that anchor on each side instead of refusing the
    missing linkage. Nothing stored is rewritten for an unlinked row, so
    per-side anchoring keeps a stage rename compatible whenever the
    enforcement itself is preserved.
    """
    source_anchor = _qa_anchor_stage(source)
    target_anchor = _qa_anchor_stage(target)
    if source_anchor is None and target_anchor is None:
        return None
    if source_anchor is None or target_anchor is None:
        return f"{binding} QA gate semantics changed"
    mapped_source_enforcement = tuple(
        (mapped_stage(source, target, gate_stage), mode)
        for gate_stage, mode in qa_enforcement_signature(source, source_anchor)
    )
    target_enforcement = qa_enforcement_signature(target, target_anchor)
    if mapped_source_enforcement != target_enforcement or source.policies.get(
        "qa"
    ) != target.policies.get("qa"):
        return f"{binding} QA gate semantics changed"
    return None


__all__ = ["phase_anchored_qa_conflict"]
