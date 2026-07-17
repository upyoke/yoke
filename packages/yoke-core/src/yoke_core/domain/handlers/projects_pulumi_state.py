"""Registered Pulumi state migration handler."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.projects_pulumi_state_migration import (
    PulumiStateMigrationError,
    migrate_pulumi_state,
)


class PulumiStateMigrateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    site_id: str
    stack_names: list[str]
    apply: StrictBool = False


class PulumiStateMigrateResponse(BaseModel):
    project: str
    site_id: str
    capability_type: str
    mode: str
    stack_names: list[str]
    source_path: str
    destination_path: str
    changed_paths: list[str]
    source_stack_set_verified: bool
    destination_verified: bool
    source_removed: bool
    sensitive_paths: list[str]
    applied: bool
    receipt_digest: str


def handle_pulumi_state_migrate(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = PulumiStateMigrateRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure(
            "payload_invalid", safe_validation_message(exc), "$.payload"
        )
    try:
        receipt = migrate_pulumi_state(
            project=parsed.project,
            site_id=parsed.site_id,
            stack_names=parsed.stack_names,
            apply=parsed.apply,
        )
    except PulumiStateMigrationError as exc:
        return _failure(exc.code, str(exc), "$.payload")
    except (LookupError, ValueError) as exc:
        return _failure("validation_error", str(exc), "$.payload")
    return HandlerOutcome(primary_success=True, result_payload=receipt)


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "PulumiStateMigrateRequest",
    "PulumiStateMigrateResponse",
    "handle_pulumi_state_migrate",
]
