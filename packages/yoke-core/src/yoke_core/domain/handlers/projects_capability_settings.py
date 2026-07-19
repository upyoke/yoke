"""Registered project capability-settings read and CAS mutation handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.settings_cas import SettingsConflictError


class CapabilitySettingsGetRequest(BaseModel):
    """Select one non-sensitive capability settings document."""

    model_config = ConfigDict(extra="forbid")

    project: str
    cap_type: str


class CapabilitySettingsSetRequest(BaseModel):
    """CAS-replace or insert one capability settings document."""

    model_config = ConfigDict(extra="forbid")

    project: str
    cap_type: str
    settings_json: str
    base_settings_json: Optional[str] = None
    create: StrictBool = False


class CapabilitySettingsMergeRequest(BaseModel):
    """Merge key paths through the read-merge-CAS loop."""

    model_config = ConfigDict(extra="forbid")

    project: str
    cap_type: str
    assignments: Dict[str, Any]


class CapabilitySettingsRemoveRequest(BaseModel):
    """CAS-remove one ordinary capability settings row."""

    model_config = ConfigDict(extra="forbid")

    project: str
    cap_type: str
    base_settings_json: str


class CapabilitySettingsResponse(BaseModel):
    project: str
    cap_type: str
    settings_json: Optional[str] = None
    changed_paths: Optional[list[str]] = None
    message: Optional[str] = None


def handle_capability_settings_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = CapabilitySettingsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_get_settings,
    )

    try:
        settings_json = cmd_capability_get_settings(parsed.project, parsed.cap_type)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")
    if settings_json is None:
        return _failure(
            "not_found",
            f"capability {parsed.cap_type!r} was not found on project "
            f"{parsed.project!r}",
            "$.payload.cap_type",
        )
    return _success(parsed.project, parsed.cap_type, settings_json)


def handle_capability_settings_set(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = CapabilitySettingsSetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_get_settings,
        cmd_capability_set_settings,
    )

    try:
        message = cmd_capability_set_settings(
            parsed.project,
            parsed.cap_type,
            parsed.settings_json,
            base_settings_json=parsed.base_settings_json,
            create=parsed.create,
        )
        settings_json = cmd_capability_get_settings(parsed.project, parsed.cap_type)
    except SettingsConflictError as exc:
        return _failure("settings_conflict", str(exc), "$.payload.base_settings_json")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")
    assert settings_json is not None
    return _success(parsed.project, parsed.cap_type, settings_json, message=message)


def handle_capability_settings_merge(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = CapabilitySettingsMergeRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_get_settings,
        cmd_capability_merge_settings,
    )

    try:
        message = cmd_capability_merge_settings(
            parsed.project, parsed.cap_type, parsed.assignments
        )
        settings_json = (
            None
            if parsed.cap_type == "pulumi-state"
            else cmd_capability_get_settings(parsed.project, parsed.cap_type)
        )
    except SettingsConflictError as exc:
        return _failure("settings_conflict", str(exc), "$.payload.assignments")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")
    if parsed.cap_type == "pulumi-state":
        return _success(
            parsed.project,
            parsed.cap_type,
            None,
            message=message,
            changed_paths=sorted(parsed.assignments),
        )
    assert settings_json is not None
    return _success(parsed.project, parsed.cap_type, settings_json, message=message)


def handle_capability_settings_remove(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = CapabilitySettingsRemoveRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _payload_invalid(exc)

    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_remove_settings,
    )

    try:
        message = cmd_capability_remove_settings(
            parsed.project,
            parsed.cap_type,
            base_settings_json=parsed.base_settings_json,
        )
    except SettingsConflictError as exc:
        return _failure("settings_conflict", str(exc), "$.payload.base_settings_json")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")
    return _success(parsed.project, parsed.cap_type, None, message=message)


def _success(
    project: str,
    cap_type: str,
    settings_json: Optional[str],
    *,
    message: Optional[str] = None,
    changed_paths: Optional[list[str]] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": project,
            "cap_type": cap_type,
            "settings_json": settings_json,
            "message": message,
            "changed_paths": changed_paths,
        },
    )


def _payload_invalid(exc: ValidationError) -> HandlerOutcome:
    return _failure("payload_invalid", safe_validation_message(exc), "$.payload")


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "CapabilitySettingsGetRequest",
    "CapabilitySettingsMergeRequest",
    "CapabilitySettingsRemoveRequest",
    "CapabilitySettingsResponse",
    "CapabilitySettingsSetRequest",
    "handle_capability_settings_get",
    "handle_capability_settings_merge",
    "handle_capability_settings_remove",
    "handle_capability_settings_set",
]
