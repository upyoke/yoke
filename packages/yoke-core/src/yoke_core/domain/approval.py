"""Shared approval and halt-state semantics for the Yoke control plane.

This module encodes the canonical approval vocabulary: halt states, approval
actions, stage authority semantics, and approval-resolution behavior.

The shell export ``.agents/skills/yoke/scripts/approval-vocabulary.sh`` is a
generated compatibility layer for shell callers and must stay aligned with this
module's constants and helpers.

Scope: SHARED control-plane semantics that apply across all workflow families.
Unlike lifecycle.py (workflow-family-local to software delivery), approval and
halt-state semantics are inherited by every workflow family.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Scope metadata
# ---------------------------------------------------------------------------

APPROVAL_SCOPE: str = "shared"

# ---------------------------------------------------------------------------
# Halt states
# ---------------------------------------------------------------------------


class HaltState(str, Enum):
    """Conditions where a deployment run or pipeline stage pauses and waits.

    These are run-level or stage-level states, NOT item lifecycle statuses.
    """

    AWAITING_APPROVAL = "awaiting-approval"
    NEEDS_CAPABILITY = "needs-capability"


# ---------------------------------------------------------------------------
# Approval actions
# ---------------------------------------------------------------------------


class ApprovalAction(str, Enum):
    """Actions that resolve halt states."""

    APPROVE = "approve"
    PROVIDE_CAPABILITY = "provide-capability"


# Mapping: which action resolves which halt state
HALT_RESOLUTION: Dict[HaltState, ApprovalAction] = {
    HaltState.AWAITING_APPROVAL: ApprovalAction.APPROVE,
    HaltState.NEEDS_CAPABILITY: ApprovalAction.PROVIDE_CAPABILITY,
}

# ---------------------------------------------------------------------------
# Stage authority
# ---------------------------------------------------------------------------

# DB column on deployment_runs that holds the current stage.
STAGE_AUTHORITY_FIELD: str = "current_stage"

# DB column on items that caches the deploy stage for display.
STAGE_CACHE_FIELD: str = "deploy_stage"

# ---------------------------------------------------------------------------
# Approval path types
# ---------------------------------------------------------------------------


class ApprovalPath(str, Enum):
    """Approval can be handled by Yoke or by an external system."""

    YOKE_HANDLED = "yoke-handled"
    EXTERNAL = "external"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def is_halt_state(state: str) -> bool:
    """Return True if *state* is a recognized halt state."""
    try:
        HaltState(state)
        return True
    except ValueError:
        return False


def is_approval_action(action: str) -> bool:
    """Return True if *action* is a recognized approval action."""
    try:
        ApprovalAction(action)
        return True
    except ValueError:
        return False


def resolve_halt_state(halt: str) -> Optional[str]:
    """Return the approval action that resolves the given halt state.

    Returns ``None`` if *halt* is not a recognized halt state.
    """
    try:
        halt_enum = HaltState(halt)
        return HALT_RESOLUTION[halt_enum].value
    except (ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Approval-resolution behavior
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowStage:
    """A single stage in a deployment flow."""

    name: str
    executor: str
    config: Dict[str, Any]


def parse_flow_stages(stages_json: str) -> List[FlowStage]:
    """Parse the JSON stages array from a deployment_flows row.

    Each stage object is expected to have at least ``name`` and ``executor``.
    Additional keys are preserved in ``config``.
    """
    raw = json.loads(stages_json)
    result = []
    for entry in raw:
        name = entry.get("name", "")
        executor = entry.get("executor", "")
        config = {k: v for k, v in entry.items() if k not in ("name", "executor")}
        result.append(FlowStage(name=name, executor=executor, config=config))
    return result


def find_stage_index(stages: Sequence[FlowStage], stage_name: str) -> Optional[int]:
    """Return the index of the stage named *stage_name*, or ``None``."""
    for i, s in enumerate(stages):
        if s.name == stage_name:
            return i
    return None


def is_human_approval_stage(stage: FlowStage) -> bool:
    """Return True if *stage* requires human approval."""
    return stage.executor == "human-approval"


@dataclass(frozen=True)
class ApprovalResolution:
    """Result of resolving an approval action against a deployment flow.

    Attributes:
        approved: True if the approval was valid and resolved.
        next_stage: The name of the stage the run should advance to.
            ``"complete"`` if the approval was at the last stage.
        error: A human-readable error message if approval was rejected.
    """

    approved: bool
    next_stage: Optional[str] = None
    error: Optional[str] = None


def resolve_approval(
    stages: Sequence[FlowStage],
    current_stage_name: str,
) -> ApprovalResolution:
    """Determine whether a stage can be approved and what comes next.

    Validates that:
    1. The current stage exists in the flow.
    2. The current stage is a ``human-approval`` executor stage.

    Returns an ``ApprovalResolution`` with ``approved=True`` and the next
    stage name on success, or ``approved=False`` with an error message.
    """
    idx = find_stage_index(stages, current_stage_name)
    if idx is None:
        return ApprovalResolution(
            approved=False,
            error=f"Stage '{current_stage_name}' does not match any stage in the flow.",
        )

    stage = stages[idx]
    if not is_human_approval_stage(stage):
        return ApprovalResolution(
            approved=False,
            error=(
                f"Stage '{current_stage_name}' is not a human-approval stage. "
                f"Cannot approve."
            ),
        )

    # Determine next stage
    if idx + 1 < len(stages):
        next_stage = stages[idx + 1].name
    else:
        next_stage = "complete"

    return ApprovalResolution(approved=True, next_stage=next_stage)
