"""Registered handlers for a project's attested no-tests posture."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class NoTestsAttestRequest(BaseModel):
    project: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class NoTestsAttestResponse(BaseModel):
    project: str
    posture: str
    reason: str
    retired_plans: List[str]


class NoTestsClearRequest(BaseModel):
    project: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


class NoTestsClearResponse(BaseModel):
    project: str
    posture: str
    reason: str
    next_step: str


def _error(code: str, message: str, jsonpath: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def _payload(
    request: FunctionCallRequest,
    model: type[BaseModel],
) -> tuple[Optional[Any], Optional[HandlerOutcome]]:
    if request.target.kind != "global":
        return None, _error(
            "target_invalid",
            f"{request.function} requires target.kind='global'",
            "$.target.kind",
        )
    try:
        return model(**(request.payload or {})), None
    except Exception as exc:  # noqa: BLE001 - surfaced as a typed function error
        return None, _error("payload_invalid", str(exc), "$.payload")


def _apply(request: FunctionCallRequest, model: type[BaseModel], write) -> HandlerOutcome:
    payload, error = _payload(request, model)
    if error is not None:
        return error

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_identity import resolve_project

    try:
        with connect() as conn:
            identity = resolve_project(conn, payload.project, required=False)
            if identity is None:
                return _error(
                    "not_found",
                    f"project {payload.project!r} not found",
                    "$.payload.project",
                )
            result: Dict[str, Any] = write(
                conn,
                project_id=int(identity.id),
                project=identity.slug,
                reason=payload.reason,
            )
    except ValueError as exc:
        return _error("incompatible", str(exc), "$.payload")

    return HandlerOutcome(result_payload={"result": result}, primary_success=True)


def handle_no_tests_attest(request: FunctionCallRequest) -> HandlerOutcome:
    """Record that a project has no suite to bind, and retire what it had.

    The retirement is not a courtesy: a project holding both an attestation and
    a registered command would materialize a command case and a review
    requirement for the same item, and the boot-time command convergence would
    then re-enter a registration the attestation refuses. Writing both halves
    here means neither surface downstream has to handle a state that can no
    longer exist.
    """
    from yoke_core.domain.project_verification_posture import attest_no_tests

    return _apply(request, NoTestsAttestRequest, attest_no_tests)


def handle_no_tests_clear(request: FunctionCallRequest) -> HandlerOutcome:
    """Remove the attestation so a project that gained a suite can bind it."""
    from yoke_core.domain.project_verification_posture import clear_no_tests

    return _apply(request, NoTestsClearRequest, clear_no_tests)


__all__ = [
    "NoTestsAttestRequest",
    "NoTestsAttestResponse",
    "NoTestsClearRequest",
    "NoTestsClearResponse",
    "handle_no_tests_attest",
    "handle_no_tests_clear",
]
