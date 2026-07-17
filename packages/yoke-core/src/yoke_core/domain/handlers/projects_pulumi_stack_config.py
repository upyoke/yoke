"""Registered stack-scoped Pulumi config materializer."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.project_renderer_pulumi_stack_config import (
    PulumiStackConfigError,
    build_pulumi_stack_config,
)


class PulumiStackConfigGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    stack: str


class PulumiStackConfigGetResponse(BaseModel):
    config_schema: int
    project_id: int
    project_slug: str
    stack_name: str
    stack_kind: str
    render_values: dict[str, Any]
    operator_state: dict[str, str]
    authority: dict[str, Any]


def handle_pulumi_stack_config_get(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    try:
        parsed = PulumiStackConfigGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _failure(
            "payload_invalid", safe_validation_message(exc), "$.payload"
        )
    conn = connect()
    try:
        payload = build_pulumi_stack_config(conn, parsed.project, parsed.stack)
    except LookupError as exc:
        return _failure("not_found", str(exc), "$.payload.project")
    except PulumiStackConfigError as exc:
        return _failure("stack_config_invalid", str(exc), "$.payload.stack")
    except ValueError as exc:
        return _failure("validation_error", str(exc), "$.payload")
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=payload)


def _failure(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


__all__ = [
    "PulumiStackConfigGetRequest",
    "PulumiStackConfigGetResponse",
    "handle_pulumi_stack_config_get",
]
