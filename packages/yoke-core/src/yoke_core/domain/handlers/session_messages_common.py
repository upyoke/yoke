"""Shared request and failure boundaries for session-message handlers."""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.session_execution import SUBAGENT_EXECUTION_PAYLOAD_KEY
from yoke_core.domain.session_message_types import SessionMessageError


def failure(code: str, message: str, path: str = "$.payload") -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=path),
    )


def parse(model: Any, request: FunctionCallRequest) -> Any:
    try:
        return model.model_validate(request.payload or {})
    except Exception as exc:
        return failure("payload_invalid", str(exc))


def require_global(request: FunctionCallRequest) -> HandlerOutcome | None:
    if request.target.kind == "global":
        return None
    return failure(
        "target_invalid",
        "session-control message functions require target.kind='global'",
        "$.target.kind",
    )


def require_top_level_message_actor(
    request: FunctionCallRequest,
) -> HandlerOutcome | None:
    """Refuse a client-attested child from acting as its parent session."""
    if request.options.get(SUBAGENT_EXECUTION_PAYLOAD_KEY) is not True:
        return None
    return failure(
        "subagent_message_forbidden",
        "in-process subagents use their harness-native parent channel; "
        "only the registered top-level session sends or acknowledges Fleet messages",
        f"$.options.{SUBAGENT_EXECUTION_PAYLOAD_KEY}",
    )


def numeric_actor_id(request: FunctionCallRequest) -> int:
    raw = str(request.actor.actor_id or "").strip()
    if not raw.isdigit():
        raise SessionMessageError(
            "actor_required",
            "verified numeric actor is required",
            jsonpath="$.actor.actor_id",
        )
    return int(raw)


def open_connection() -> Any:
    from yoke_core.domain.db_helpers import connect

    return connect()


def domain_error(exc: Exception) -> HandlerOutcome:
    if isinstance(exc, SessionMessageError):
        return failure(exc.code, str(exc), exc.jsonpath)
    if isinstance(exc, LookupError):
        return failure("target_not_found", str(exc))
    return failure("message_rejected", str(exc))


__all__ = [
    "domain_error",
    "failure",
    "numeric_actor_id",
    "open_connection",
    "parse",
    "require_global",
    "require_top_level_message_actor",
]
