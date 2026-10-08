"""Registered read: propose level changes from the current model catalog.

Model refresh researches and publishes catalog facts first, then asks this
function what those facts mean for the universe levels. With no ``changes``
it extrapolates them from the catalog; with ``changes`` it applies the
author's list instead. Either way it returns the resulting levels document
and refuses an option whose effort or context window the model's provider
does not publish. Nothing is written: approval stores the returned document
with ``yoke universe levels set``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.level_proposals import (
    apply_level_changes,
    generate_level_changes,
    published_capability_conflicts,
    refuse_capability_conflicts,
    unplaced_models,
)
from yoke_contracts.levels import LevelsError, levels_payload
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

FUNCTION_ID = "models.level_proposal.run"
APPLY_COMMAND = "yoke universe levels set --stdin"


class ModelsLevelProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    changes: Optional[List[Dict[str, Any]]] = None


class ModelsLevelProposalResponse(BaseModel):
    revision_id: str
    base_source: str
    generated: bool
    changes: List[Dict[str, Any]]
    levels: List[Dict[str, Any]]
    unverified: List[Dict[str, Any]]
    unplaced_models: List[Dict[str, Any]]
    apply_command: str


def _failure(code: str, message: str, jsonpath: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_models_level_proposal(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        spec = ModelsLevelProposalRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.model_reference_store import revision_at
    from yoke_core.domain.universe_levels import UniverseLevelsError, effective_levels

    try:
        with connect() as conn:
            revision = revision_at(conn)
            base, source = effective_levels(conn, None)
    except ModelReferenceError as exc:
        return _failure(
            exc.code,
            f"{exc}. Recovery: publish a catalog revision with `yoke models "
            "publish` before proposing level changes.",
        )
    except (LevelsError, UniverseLevelsError) as exc:
        return _failure(
            getattr(exc, "code", "levels_document_invalid"),
            f"{exc}. Recovery: store a valid document with "
            "`yoke universe levels set --stdin`.",
        )
    records = revision["records"]
    generated = spec.changes is None
    try:
        if generated:
            changes = generate_level_changes(base, records)
        else:
            changes = list(spec.changes or [])
        levels = apply_level_changes(base, changes)
        conflicts, unverified = published_capability_conflicts(levels, records)
        refuse_capability_conflicts(conflicts)
    except LevelsError as exc:
        return _failure(
            exc.code, f"{exc.field}: {exc.detail}", f"$.payload.{exc.field}"
        )
    return HandlerOutcome(
        result_payload={
            "revision_id": revision["revision_id"],
            "base_source": source,
            "generated": generated,
            "changes": changes,
            "levels": levels_payload(levels),
            "unverified": unverified,
            "unplaced_models": unplaced_models(levels, records),
            "apply_command": APPLY_COMMAND,
        }
    )


__all__ = [
    "APPLY_COMMAND",
    "FUNCTION_ID",
    "ModelsLevelProposalRequest",
    "ModelsLevelProposalResponse",
    "handle_models_level_proposal",
]
