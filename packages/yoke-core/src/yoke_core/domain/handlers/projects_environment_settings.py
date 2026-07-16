"""Registered project environment-settings read and CAS merge handlers."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.settings_cas import SettingsConflictError


class EnvironmentSettingsGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    environment_id: str


class EnvironmentSettingsMergeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    environment_id: str
    assignments: Dict[str, Any]


class EnvironmentSettingsResponse(BaseModel):
    project: str
    environment_id: str
    settings_json: str
    message: Optional[str] = None


def handle_environment_settings_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = EnvironmentSettingsGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure(
            "payload_invalid", safe_validation_message(exc), "$.payload"
        )
    mismatch = _environment_project_mismatch(
        parsed.environment_id, parsed.project
    )
    if mismatch is not None:
        return mismatch

    from yoke_core.domain.projects_environments_settings import (
        cmd_environment_get_settings,
    )

    try:
        settings_json = cmd_environment_get_settings(parsed.environment_id)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.environment_id")
    return _success(parsed.project, parsed.environment_id, settings_json)


def handle_environment_settings_merge(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = EnvironmentSettingsMergeRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure(
            "payload_invalid", safe_validation_message(exc), "$.payload"
        )
    mismatch = _environment_project_mismatch(
        parsed.environment_id, parsed.project
    )
    if mismatch is not None:
        return mismatch

    from yoke_core.domain.projects_environments_settings import (
        cmd_environment_get_settings,
        cmd_environment_merge_settings,
    )

    try:
        message = cmd_environment_merge_settings(
            parsed.environment_id, parsed.assignments
        )
        settings_json = cmd_environment_get_settings(parsed.environment_id)
    except SettingsConflictError as exc:
        return _failure(
            "settings_conflict", str(exc), "$.payload.assignments"
        )
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.environment_id")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload.assignments")
    return _success(
        parsed.project,
        parsed.environment_id,
        settings_json,
        message=message,
    )


def _environment_project_mismatch(
    environment_id: str, project: str
) -> Optional[HandlerOutcome]:
    from yoke_core.domain.db_helpers import connect

    conn = connect()
    try:
        project_id = resolve_project_id(conn, project)
        row = conn.execute(
            "SELECT s.project_id FROM environments e "
            "JOIN sites s ON s.id=e.site WHERE e.id=%s",
            (environment_id,),
        ).fetchone()
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    finally:
        conn.close()
    if row is None:
        return _failure(
            "not_found",
            f"environment {environment_id!r} was not found",
            "$.payload.environment_id",
        )
    if int(row[0]) != project_id:
        return _failure(
            "project_mismatch",
            f"environment {environment_id!r} does not belong to project "
            f"{project!r}",
            "$.payload.project",
        )
    return None


def _success(
    project: str,
    environment_id: str,
    settings_json: str,
    *,
    message: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "project": project,
            "environment_id": environment_id,
            "settings_json": settings_json,
            "message": message,
        },
    )


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "EnvironmentSettingsGetRequest",
    "EnvironmentSettingsMergeRequest",
    "EnvironmentSettingsResponse",
    "handle_environment_settings_get",
    "handle_environment_settings_merge",
]
