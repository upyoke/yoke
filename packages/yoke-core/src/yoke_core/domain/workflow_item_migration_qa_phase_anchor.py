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


def _qa_conflict_message(
    binding: str,
    source_anchor: str | None,
    target_anchor: str | None,
    requirement_id: int | None,
) -> str:
    source_label = repr(source_anchor) if source_anchor is not None else "<none>"
    target_label = repr(target_anchor) if target_anchor is not None else "<none>"
    detail = (
        f"{binding} QA gate semantics changed "
        f"(source anchor stage {source_label}; target anchor stage {target_label})"
    )
    if requirement_id is None:
        return (
            f"{detail}; accept the current workflow pin when the target QA "
            "enforcement change is intentional"
        )
    return (
        f"{detail}; waive with `yoke qa requirement waive --requirement-id "
        f'{requirement_id} --rationale "<reason>" --source operator --force`, '
        "or accept the current workflow pin when the target QA enforcement "
        "change is intentional"
    )


def qa_conflict(
    binding: str,
    source_enforcement: tuple[tuple[str, str | None], ...],
    target_enforcement: tuple[tuple[str, str | None], ...],
    requirement_id: int | None,
) -> str:
    """Render one actionable QA migration conflict from enforcement paths."""
    source_anchor = source_enforcement[0][0] if source_enforcement else None
    target_anchor = target_enforcement[0][0] if target_enforcement else None
    return _qa_conflict_message(
        binding,
        source_anchor,
        target_anchor,
        requirement_id,
    )


def phase_anchored_qa_conflict(
    source: WorkflowRuntime,
    target: WorkflowRuntime,
    *,
    binding: str,
    requirement_id: int,
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
        return _qa_conflict_message(
            binding, source_anchor, target_anchor, requirement_id
        )
    mapped_source_enforcement = tuple(
        (mapped_stage(source, target, gate_stage), mode)
        for gate_stage, mode in qa_enforcement_signature(source, source_anchor)
    )
    target_enforcement = qa_enforcement_signature(target, target_anchor)
    if mapped_source_enforcement != target_enforcement or source.policies.get(
        "qa"
    ) != target.policies.get("qa"):
        return _qa_conflict_message(
            binding, source_anchor, target_anchor, requirement_id
        )
    return None


__all__ = ["phase_anchored_qa_conflict", "qa_conflict"]
