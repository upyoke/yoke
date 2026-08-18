"""Registered handler for capability-routed release-pin recording."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.release_pin_record import (
    ReleasePinCapabilityInvalid,
    ReleasePinCapabilityMissing,
    ReleasePinConfiguredLeafNotScalar,
    ReleasePinProjectMismatch,
    record_release_pin,
)
from yoke_core.domain.settings_cas import SettingsConflictError


class ReleasePinRecordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    pin: str = Field(min_length=1, max_length=200)


class ReleasePinRecordResponse(BaseModel):
    project: str
    environment: str
    settings_path: str
    pin: str
    changed: bool


def handle_release_pin_record(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = ReleasePinRecordRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")
    target_project = str(request.target.project_id or "").strip() or None
    authorized_project_id = (request.options or {}).get("authorized_project_id")
    try:
        receipt = record_release_pin(
            parsed.project,
            parsed.environment,
            parsed.pin,
            authorized_project_id=(
                int(authorized_project_id)
                if authorized_project_id is not None
                else None
            ),
            target_project=target_project,
        )
    except ReleasePinCapabilityMissing as exc:
        return _failure("capability_missing", str(exc), "$.payload.project")
    except ReleasePinCapabilityInvalid as exc:
        return _failure("capability_invalid", str(exc), "$.payload.project")
    except ReleasePinConfiguredLeafNotScalar as exc:
        return _failure(
            "configured_leaf_not_scalar",
            str(exc),
            "$.payload.environment",
        )
    except ReleasePinProjectMismatch as exc:
        return _failure("project_mismatch", str(exc), "$.payload.project")
    except SettingsConflictError as exc:
        return _failure("settings_conflict", str(exc), "$.payload.pin")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.environment")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload.pin")
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": receipt.project,
            "environment": receipt.environment,
            "settings_path": receipt.settings_path,
            "pin": receipt.pin,
            "changed": receipt.changed,
        },
    )


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "ReleasePinRecordRequest",
    "ReleasePinRecordResponse",
    "handle_release_pin_record",
]
