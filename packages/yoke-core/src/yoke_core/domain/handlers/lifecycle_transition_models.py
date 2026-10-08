"""Wire models for stage transitions and their worker handoffs."""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence

from pydantic import BaseModel, Field


class LifecycleTransitionRequest(BaseModel):
    """Payload for ``lifecycle.transition``."""

    target_status: str = Field(
        ..., description="New value for items.status (the canonical lifecycle name)."
    )
    source_status: Optional[str] = Field(
        None,
        description=(
            "Optional precondition: handler verifies items.status matches "
            "before issuing the write."
        ),
    )
    reason: Optional[str] = Field(
        None,
        description=(
            "Human-readable rationale recorded with the call. When cancelling, "
            "this must be a non-empty one-line reason and is stored in "
            "items.resolution."
        ),
    )
    done_nonce_verified: bool = False
    force: bool = False
    qa_bypass: bool = False
    containment_attestations: Optional[Sequence[Mapping[str, Any]]] = Field(
        None,
        description=(
            "Containment verdicts the caller's own checkout answered, for "
            "gates on a control plane that holds none. Consulted only where "
            "this host's repository sources could not answer, and only for "
            "the exact pair of commits each one names."
        ),
    )


class LifecycleTransitionResponse(BaseModel):
    """Successful result envelope."""

    item_id: int
    from_status: str
    to_status: str
    reason: Optional[str] = None
    execution_instructions: list[dict] = Field(default_factory=list)
    log: str = ""
    #: The bound skill whose segment the target entered, when it changed.
    skill_handoff: Optional[Dict[str, str]] = None
    handoff: Optional[Dict[str, str]] = None
