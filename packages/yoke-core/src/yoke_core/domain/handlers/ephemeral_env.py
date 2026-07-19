"""Registered ephemeral environment lifecycle handlers."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class EphemeralEnvUpdateRequest(BaseModel):
    env_id: int
    field: str
    value: str


class EphemeralEnvCreateRequest(BaseModel):
    project: str
    branch: str
    item: str = ""
    workflow_run_id: str = ""
    github_ref: str = ""


class EphemeralEnvGetRequest(BaseModel):
    project: str
    branch: str


class EphemeralEnvGetResponse(BaseModel):
    environment: dict[str, Any]


class EphemeralEnvCreateResponse(BaseModel):
    env_id: int
    project: str
    branch: str


class EphemeralEnvUpdateResponse(BaseModel):
    env_id: int
    field: str
    value: str
    message: str
    updated: bool


def _error(
    code: str,
    message: str,
    *,
    jsonpath: Optional[str] = None,
) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _require_text(payload: dict[str, Any], key: str) -> str | HandlerOutcome:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        return _error(
            "payload_invalid",
            f"{key} is required",
            jsonpath=f"$.payload.{key}",
        )
    return value.strip()


def _env_id(payload: dict[str, Any]) -> int | HandlerOutcome:
    value = payload.get("env_id")
    try:
        env_id = int(value)
    except (TypeError, ValueError):
        return _error(
            "payload_invalid",
            "env_id must be an integer",
            jsonpath="$.payload.env_id",
        )
    if env_id <= 0:
        return _error(
            "payload_invalid",
            "env_id must be positive",
            jsonpath="$.payload.env_id",
        )
    return env_id


def handle_ephemeral_env_update(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "ephemeral_env.update requires target.kind='global'",
            jsonpath="$.target.kind",
        )

    payload = request.payload or {}
    env_id = _env_id(payload)
    if isinstance(env_id, HandlerOutcome):
        return env_id
    field = _require_text(payload, "field")
    if isinstance(field, HandlerOutcome):
        return field
    value = _require_text(payload, "value")
    if isinstance(value, HandlerOutcome):
        return value

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ephemeral_env import cmd_update

    conn = connect()
    try:
        message = cmd_update(conn, env_id, field, value)
    except LookupError as exc:
        return _error("not_found", str(exc), jsonpath="$.payload.env_id")
    except ValueError as exc:
        return _error("invalid_field", str(exc), jsonpath="$.payload.field")
    finally:
        conn.close()

    return HandlerOutcome(
        result_payload={
            "env_id": env_id,
            "field": field,
            "value": value,
            "message": message,
            "updated": True,
        },
        primary_success=True,
    )


def handle_ephemeral_env_get(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "ephemeral_env.get requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    try:
        payload = EphemeralEnvGetRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"payload invalid: {exc}")
    if not payload.project.strip() or not payload.branch.strip():
        return _error(
            "payload_invalid",
            "project and branch are required",
            jsonpath="$.payload",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ephemeral_env import EPHEMERAL_ENV_FIELDS, cmd_get
    from yoke_core.domain.handlers.deployment_common import pipe_to_dict

    try:
        with connect() as conn:
            raw = cmd_get(conn, payload.project.strip(), payload.branch.strip())
    except LookupError as exc:
        return _error("not_found", str(exc), jsonpath="$.payload.branch")
    return HandlerOutcome(
        result_payload=EphemeralEnvGetResponse(
            environment=pipe_to_dict(raw, EPHEMERAL_ENV_FIELDS)
        ).model_dump(),
        primary_success=True,
    )


def handle_ephemeral_env_create(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "ephemeral_env.create requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    try:
        payload = EphemeralEnvCreateRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _error("payload_invalid", f"payload invalid: {exc}")
    if not payload.project.strip() or not payload.branch.strip():
        return _error(
            "payload_invalid",
            "project and branch are required",
            jsonpath="$.payload",
        )

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.ephemeral_env import cmd_create

    try:
        with connect() as conn:
            raw_env_id = cmd_create(
                conn,
                payload.project.strip(),
                payload.branch.strip(),
                payload.item.strip(),
                payload.workflow_run_id.strip(),
                payload.github_ref.strip(),
            )
    except (LookupError, ValueError) as exc:
        return _error("create_rejected", str(exc), jsonpath="$.payload")
    return HandlerOutcome(
        result_payload=EphemeralEnvCreateResponse(
            env_id=int(raw_env_id),
            project=payload.project.strip(),
            branch=payload.branch.strip(),
        ).model_dump(),
        primary_success=True,
    )


__all__ = [
    "EphemeralEnvCreateRequest",
    "EphemeralEnvCreateResponse",
    "EphemeralEnvGetRequest",
    "EphemeralEnvGetResponse",
    "EphemeralEnvUpdateRequest",
    "EphemeralEnvUpdateResponse",
    "handle_ephemeral_env_create",
    "handle_ephemeral_env_get",
    "handle_ephemeral_env_update",
]
