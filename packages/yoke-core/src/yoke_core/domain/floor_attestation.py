"""Floor close-out: agent-attested evidence without a merge SHA.

Work that produces no merge commit — a ``--no-changes`` finding, or any
item whose pinned workflow delivers merge-free — closes on the agent
account plus the observed changes. That evidence carries the floor rung
instead of SHAs, and it is a first-class close, not an error bypass.
Outward-action approval gating is a future approvals-primitive concern;
:func:`outward_action_approval_seam` is the named hook and currently
always passes.
"""

from __future__ import annotations

from typing import Mapping, Optional

FLOOR_RUNG_AGENT_ATTESTED = "agent-attested"
DIRECT_EVIDENCE_WORKFLOWS = frozenset({"dash", "task"})


def resolved_floor_rung(
    *,
    no_changes: bool,
    merge_free_delivery: bool,
    merge_sha: str = "",
) -> str:
    """Stamp the agent-attested floor when no merge answers for the work.

    A landed merge is its own satisfier even on a no-changes close, so a
    recorded merge SHA leaves the record unstamped and the SHA is what
    later reads match against.
    """
    if str(merge_sha or "").strip():
        return ""
    if no_changes or merge_free_delivery:
        return FLOOR_RUNG_AGENT_ATTESTED
    return ""


def sha_fields_required(*, no_changes: bool, floor_rung: str = "") -> bool:
    """Whether commit and merge SHAs are obligatory on this evidence record."""
    if no_changes:
        return False
    return str(floor_rung or "").strip() != FLOOR_RUNG_AGENT_ATTESTED


def outward_action_approval_seam() -> Optional[dict]:
    """Named seam for future outward-action approval gating. Not built."""
    return None


def evidence_workflow_mismatch(workflow_id: str, item_id: int) -> Optional[str]:
    """Reject evidence writes on workflows that do not own this record."""
    if str(workflow_id) in DIRECT_EVIDENCE_WORKFLOWS:
        return None
    return (
        f"item {item_id} uses workflow {workflow_id!r}, not a "
        "direct-evidence workflow"
    )


def floor_rung_missing(evidence: Mapping[str, object]) -> bool:
    """Whether the recorded floor stamp is absent."""
    return str(evidence.get("floor_rung") or "").strip() == ""


__all__ = [
    "DIRECT_EVIDENCE_WORKFLOWS",
    "FLOOR_RUNG_AGENT_ATTESTED",
    "evidence_workflow_mismatch",
    "floor_rung_missing",
    "outward_action_approval_seam",
    "resolved_floor_rung",
    "sha_fields_required",
]
