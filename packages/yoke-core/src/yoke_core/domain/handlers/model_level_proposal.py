"""Registered read: propose level changes from the current model catalog.

Model refresh researches and publishes catalog facts first, then asks this
function what those facts mean for the universe levels. With no ``changes``
it extrapolates them from the catalog; with ``changes`` it applies the
author's list instead. Either way it returns the resulting levels document
and refuses a row whose minimum effort the model's provider does not publish.
Nothing is written. Approval of a document equal to the shipped defaults
applies with ``yoke settings unset levels`` so the universe keeps following
shipped defaults; any other document applies with ``yoke settings set levels``,
which stops the universe following future shipped defaults.
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
    unplaceable_models,
    unplaced_models,
)
from yoke_contracts.levels import LevelsError, default_levels, levels_payload
from yoke_contracts.model_reference_records import ModelReferenceError
from yoke_core.domain.pydantic_validation_safety import safe_validation_message

FUNCTION_ID = "models.level_proposal.run"
APPLY_COMMAND = "yoke settings set levels -"
RESET_COMMAND = "yoke settings unset levels"


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
    unplaceable_models: List[Dict[str, Any]]
    equals_shipped_defaults: bool
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
            "`yoke settings set levels -`.",
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
    equals_defaults = levels == default_levels()
    return HandlerOutcome(
        result_payload={
            "revision_id": revision["revision_id"],
            "base_source": source,
            "generated": generated,
            "changes": changes,
            "levels": levels_payload(levels),
            "unverified": unverified,
            "unplaced_models": unplaced_models(levels, records),
            "unplaceable_models": unplaceable_models(levels, records),
            "equals_shipped_defaults": equals_defaults,
            "apply_command": RESET_COMMAND if equals_defaults else APPLY_COMMAND,
        }
    )


__all__ = [
    "APPLY_COMMAND",
    "FUNCTION_ID",
    "RESET_COMMAND",
    "ModelsLevelProposalRequest",
    "ModelsLevelProposalResponse",
    "handle_models_level_proposal",
]
