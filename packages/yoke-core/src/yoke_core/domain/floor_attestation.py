"""Floor close-out: agent-attested evidence without a merge SHA.

Work that produces no merge commit — a ``--no-changes`` finding, or any
item whose pinned workflow delivers merge-free — closes on the agent
account plus the observed changes. The evidence carries that account;
``item_gate_satisfactions`` carries the canonical ``agent_attested`` rung.
It is a first-class close, not an error bypass.
Outward-action approval gating is a future approvals-primitive concern;
:func:`outward_action_approval_seam` is the named hook and currently
always passes.
"""

from __future__ import annotations

from typing import Optional

DIRECT_EVIDENCE_WORKFLOWS = frozenset({"dash", "task"})


def uses_agent_attested_floor(
    *,
    no_changes: bool,
    merge_free_delivery: bool,
    merge_sha: str = "",
) -> bool:
    """Whether no merge answers and the done obligation uses its floor rung.

    A landed merge is its own satisfier even on a no-changes close, so a
    recorded merge SHA leaves the evidence commit-bound and the merge is what
    later reads match against.
    """
    if str(merge_sha or "").strip():
        return False
    return bool(no_changes or merge_free_delivery)


def sha_fields_required(*, no_changes: bool, agent_attested: bool) -> bool:
    """Whether commit and merge SHAs are obligatory on this evidence record."""
    return not no_changes and not agent_attested


def outward_action_approval_seam() -> Optional[dict]:
    """Named seam for future outward-action approval gating. Not built."""
    return None


def evidence_workflow_mismatch(workflow_id: str, item_id: int) -> Optional[str]:
    """Reject evidence writes on workflows that do not own this record."""
    if str(workflow_id) in DIRECT_EVIDENCE_WORKFLOWS:
        return None
    return (
        f"item {item_id} uses workflow {workflow_id!r}, not a direct-evidence workflow"
    )


__all__ = [
    "DIRECT_EVIDENCE_WORKFLOWS",
    "evidence_workflow_mismatch",
    "outward_action_approval_seam",
    "sha_fields_required",
    "uses_agent_attested_floor",
]
