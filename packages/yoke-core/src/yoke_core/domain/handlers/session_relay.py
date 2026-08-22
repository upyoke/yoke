"""Registered-function handlers for authenticated machine-relay polling."""

from __future__ import annotations

from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain.session_relay_types import (
    MAX_RELAY_LONG_POLL_SECONDS,
    RelayHeartbeat,
    SessionRelayError,
)


class RelayClaimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    machine_id: str
    hostname: str
    relay_version: str
    projects: list[int]
    surfaces: Dict[str, str]
    wait_seconds: int = Field(
        default=MAX_RELAY_LONG_POLL_SECONDS,
        ge=0,
        le=MAX_RELAY_LONG_POLL_SECONDS,
    )


class RelayClaimResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    relay_id: str
    machine_id: str
    state: Literal["active", "idle"]
    connected_until: str
    next_poll_seconds: int
    job: Dict[str, Any] | None = None


class RelayReportPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relay_id: str
    job_kind: Literal["launch", "wake"]
    job_id: str
    lease_id: str
    result: str
    native_id: str | None = None
    adapter_revision: str | None = None
    evidence: Dict[str, Any] = Field(default_factory=dict)


class RelayReportResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    job_kind: Literal["launch", "wake"]
    result: Dict[str, Any]


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


def handle_relay_claim(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = RelayClaimPayload.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_relay import claim_relay_job

    conn = connect()
    try:
        try:
            outcome = claim_relay_job(
                conn,
                RelayHeartbeat(
                    relay_id=payload.relay_id,
                    machine_id=payload.machine_id,
                    hostname=payload.hostname,
                    relay_version=payload.relay_version,
                    surface_versions=payload.surfaces,
                    project_ids=payload.projects,
                ),
                wait_seconds=payload.wait_seconds,
            )
        except (SessionRelayError, ValueError) as exc:
            return _failure(getattr(exc, "code", "relay_claim_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=outcome.to_dict())


def handle_relay_report(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        payload = RelayReportPayload.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_relay import report_relay_job

    conn = connect()
    try:
        try:
            result = report_relay_job(
                conn,
                relay_id=payload.relay_id,
                job_kind=payload.job_kind,
                job_id=payload.job_id,
                lease_id=payload.lease_id,
                result_code=payload.result,
                native_session_id=payload.native_id,
                adapter_revision=payload.adapter_revision,
                evidence=payload.evidence,
            )
        except (SessionRelayError, ValueError) as exc:
            return _failure(getattr(exc, "code", "relay_report_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={"job_kind": payload.job_kind, "result": result},
    )


__all__ = [
    "RelayClaimPayload",
    "RelayClaimResponse",
    "RelayReportPayload",
    "RelayReportResponse",
    "handle_relay_claim",
    "handle_relay_report",
]
