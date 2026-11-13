"""Registered handler for dropping one installed Pack's record from a project."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.runtime_ports.packs import get_packs
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class PacksRemoveRequest(BaseModel):
    """Inputs for dropping one installed Pack's record from a project."""

    model_config = ConfigDict(extra="forbid")

    project: str
    pack: str
    repo_root: str | None = None
    apply: bool = False


class PacksRemoveResponse(BaseModel):
    """Reviewable result from a machine-local Pack removal."""

    operation: str
    project_id: int
    project_slug: str
    repo_root: str
    pack: str
    version: str
    catalog: dict[str, str]
    drops: list[str]
    kept_project_files: list[str]
    remaining_packs: list[str]
    applied: bool
    receipt: str
    projection: dict[str, Any] | None = None


def handle_packs_remove(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = PacksRemoveRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    packs = get_packs()
    try:
        result = packs.run_pack_remove(
            parsed.repo_root,
            project=parsed.project,
            pack=parsed.pack,
            apply=parsed.apply,
            session_id=request.actor.session_id or None,
        )
    except packs.PackClientError as exc:
        return _failure("pack_remove_failed", str(exc))
    return HandlerOutcome(primary_success=True, result_payload=result)


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


__all__ = ["PacksRemoveRequest", "PacksRemoveResponse", "handle_packs_remove"]
