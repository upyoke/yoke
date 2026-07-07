"""Yoke function-call envelope models.

Canonical Pydantic request/response shapes shared by every function family
and every adapter (CLI, in-process Python, FastAPI HTTP). The envelope is
the boundary contract: JSON at the edge, typed Python at the core.

Public surface:

- :class:`ActorContext`, :class:`TargetRef` — request sub-models.
- :class:`FunctionCallRequest`, :class:`FunctionCallResponse` — envelope.
- :class:`FunctionWarning`, :class:`FunctionError`, :class:`HandlerOutcome`.
- :data:`function_id_pattern`, :func:`validate_function_id` — id regex.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER


# ``<family>.<subfamily>.<operation>`` or ``<family>.<operation>`` — each
# segment is one or more lowercase letters / digits / underscores,
# leading with a letter; segments are separated by a single dot.
# Two-segment ids are admitted for families with a single operation
# surface (``db_claim.amend``); three-segment ids remain the dominant
# shape across every other family.
function_id_pattern = re.compile(
    r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)?$"
)


def validate_function_id(s: str) -> bool:
    """Return True when *s* matches ``<family>.<subfamily>.<operation>``
    or the two-segment shorthand ``<family>.<operation>`` reserved for
    families with one operation."""
    if not isinstance(s, str):
        return False
    return function_id_pattern.match(s) is not None


class ActorContext(BaseModel):
    """Calling actor identity.

    ``session_id`` is required and identifies the harness session that
    sourced the call. ``actor_id`` is optional and resolves server-side
    from ``harness_sessions`` keyed on the bound session_id when omitted
    (or blank); a supplied value must agree with the resolved value, or
    the call is denied via the ``actor_id_mismatch`` actor-identity gate.
    """

    actor_id: Optional[str] = Field(
        default=None,
        description="Stable actor identity; resolved server-side from session_id when omitted.",
    )
    session_id: str = Field(..., description="Harness session id, used for claim verification.")


class TargetRef(BaseModel):
    """Discriminated target reference. ``kind`` selects which keys are meaningful.

    ``item_ref`` carries a raw public item reference (``PREFIX-N`` or a
    bare project-local number) that the dispatcher resolves server-side
    into ``item_id`` before permission/claim checks — clients never need
    DB access to build an item-targeted envelope (relay contract,
    CLI grammar contract). ``project_id`` doubles as the client-supplied
    project context for bare numeric refs; it stays authoritative-free
    (the server validates it).
    """

    kind: Literal[
        "item",
        "epic_task",
        "section",
        "claim",
        "db_claim",
        "path_claim",
        "project_structure",
        "qa_requirement",
        "workflow_run",
        "global",
    ]
    item_id: Optional[int] = None
    item_ref: Optional[str] = None
    epic_id: Optional[int] = None
    task_num: Optional[int] = None
    section_name: Optional[str] = None
    claim_id: Optional[int] = None
    path_claim_id: Optional[int] = None
    db_claim_id: Optional[int] = None
    project_id: Optional[str] = None
    qa_requirement_id: Optional[int] = None
    workflow_run_id: Optional[str] = None


class FunctionWarning(BaseModel):
    """One downstream-degraded step. Multiple may appear per response."""

    code: str
    step: str
    detail: str
    recovery_function: Optional[str] = None


class FunctionError(BaseModel):
    """Populated when ``success=False`` on the response envelope.

    Every constructed error envelope carries the field-note footer
    on ``recovery_hint``. The footer routes operators and agents
    to ``yoke ouroboros field-note append`` so failure surfaces close
    the Ouroboros learning loop at the point of friction. Idempotency is
    structural — re-constructing or re-validating a ``FunctionError`` that
    already carries the footer is a no-op, never a double-append.
    """

    code: str
    message: str
    jsonpath: Optional[str] = None
    recovery_hint: Optional[str] = None

    @model_validator(mode="after")
    def _append_field_note_footer(self) -> "FunctionError":
        # Idempotent: if the footer is already in recovery_hint, leave it
        # alone — Pydantic re-runs validators on model copy / round-trip.
        existing = self.recovery_hint
        if existing and _FIELD_NOTE_FOOTER in existing:
            return self
        if existing:
            object.__setattr__(
                self, "recovery_hint",
                f"{existing}\n\n{_FIELD_NOTE_FOOTER}",
            )
        else:
            object.__setattr__(self, "recovery_hint", _FIELD_NOTE_FOOTER)
        return self


class FunctionCallRequest(BaseModel):
    """Canonical request envelope. Family-specific payload is opaque to the dispatcher."""

    function: str
    version: str = "v1"
    actor: ActorContext
    target: TargetRef
    request_id: Optional[str] = None
    intent: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    preconditions: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)


class FunctionCallResponse(BaseModel):
    """Canonical response envelope. ``warnings[]`` carries downstream-degraded steps."""

    success: bool
    function: str
    version: str
    request_id: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[FunctionWarning] = Field(default_factory=list)
    error: Optional[FunctionError] = None
    event_ids: List[int] = Field(default_factory=list)


@dataclass
class HandlerOutcome:
    """Internal handler return shape consumed by the dispatcher.

    Handlers populate ``result_payload`` and ``primary_success`` for the
    primary mutation. Downstream side-effects (board rebuild, GitHub
    sync, packet drift gate) are wrapped by the dispatcher; per-step
    failures append to ``warnings`` and emit ``DispatcherDownstreamDegraded``.
    """

    result_payload: Dict[str, Any] = field(default_factory=dict)
    primary_success: bool = True
    warnings: List[FunctionWarning] = field(default_factory=list)
    error: Optional[FunctionError] = None
    side_effects_to_run: List[str] = field(default_factory=list)
    handler_event_ids: List[int] = field(default_factory=list)


__all__ = [
    "ActorContext",
    "TargetRef",
    "FunctionCallRequest",
    "FunctionCallResponse",
    "FunctionWarning",
    "FunctionError",
    "HandlerOutcome",
    "function_id_pattern",
    "validate_function_id",
]
