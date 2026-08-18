"""Registered project environment-settings read and CAS merge handlers."""

from __future__ import annotations

import json
from typing import Any, Dict

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import environment_reference
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.settings_cas import SettingsConflictError
from yoke_core.domain.settings_cas import read_key_path


class EnvironmentSettingsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    environment: str
    paths: list[str]


class EnvironmentSettingsMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    environment: str
    assignments: Dict[str, Any]


class EnvironmentSettingsProjectionResponse(BaseModel):
    project: str
    environment: str
    values: Dict[str, Any]


class EnvironmentSettingsMergeResponse(BaseModel):
    project: str
    environment: str
    changed_paths: list[str]
    message: str


def handle_environment_settings_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = EnvironmentSettingsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")
    resolved = _resolved_environment(
        parsed.project,
        parsed.environment,
        authorized_project_id=(request.options or {}).get("authorized_project_id"),
    )
    if isinstance(resolved, HandlerOutcome):
        return resolved

    from yoke_core.domain.projects_environments_settings import (
        cmd_environment_get_settings,
    )

    try:
        settings_json = cmd_environment_get_settings(resolved.id)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.environment")
    try:
        values = _project_scalar_paths(settings_json, parsed.paths)
    except ValueError as exc:
        return _failure("projection_invalid", str(exc), "$.payload.paths")
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": parsed.project,
            "environment": resolved.name,
            "values": values,
        },
    )


def handle_environment_settings_merge(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = EnvironmentSettingsMergeRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc), "$.payload")
    resolved = _resolved_environment(
        parsed.project,
        parsed.environment,
        authorized_project_id=(request.options or {}).get("authorized_project_id"),
    )
    if isinstance(resolved, HandlerOutcome):
        return resolved

    from yoke_core.domain.projects_environments_settings import (
        cmd_environment_merge_settings,
    )

    try:
        message = cmd_environment_merge_settings(resolved.id, parsed.assignments)
    except SettingsConflictError as exc:
        return _failure("settings_conflict", str(exc), "$.payload.assignments")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.environment")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload.assignments")
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": parsed.project,
            "environment": resolved.name,
            "changed_paths": sorted(parsed.assignments),
            "message": message,
        },
    )


def _resolved_environment(
    project: str,
    environment: str,
    *,
    authorized_project_id: Any = None,
) -> Any:
    """Resolve the named environment, or the failure explaining why not.

    Resolution is the ownership check: a name only resolves inside the project
    that registers it, so comparing a supplied id against the project would be
    asking the same question twice.
    """
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        project_ref = (
            int(authorized_project_id) if authorized_project_id is not None else project
        )
        project_id = resolve_project_id(conn, project_ref)
        return environment_reference.resolve(
            conn, project_id=project_id, name=environment
        )
    except environment_reference.EnvironmentReferenceError as exc:
        return _failure("not_found", str(exc), "$.payload.environment")
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    finally:
        conn.close()


def _project_scalar_paths(settings_json: str, paths: list[str]) -> dict[str, Any]:
    """Return named scalar leaves; numeric segments traverse array entries."""
    if not paths:
        raise ValueError("at least one JSON path is required")
    try:
        document = json.loads(settings_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("stored environment settings are not valid JSON") from exc
    if not isinstance(document, dict):
        raise ValueError("stored environment settings must be a JSON object")
    values: dict[str, Any] = {}
    for path in paths:
        normalized = str(path or "").strip()
        value = read_key_path(document, normalized)
        if isinstance(value, (dict, list)):
            raise ValueError(
                f"JSON path {normalized!r} selects a container; name one "
                "scalar leaf instead"
            )
        values[normalized] = value
    return values


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "EnvironmentSettingsGetRequest",
    "EnvironmentSettingsMergeRequest",
    "EnvironmentSettingsMergeResponse",
    "EnvironmentSettingsProjectionResponse",
    "handle_environment_settings_get",
    "handle_environment_settings_merge",
]
