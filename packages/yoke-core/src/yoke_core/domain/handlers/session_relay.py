"""Registered-function handlers for authenticated machine-relay polling."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.session_control.models import (
    RelayClaimRequest,
    RelayClaimResponse,
    RelayListRequest,
    RelayListResponse,
    RelayReportRequest,
    RelayReportResponse,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
)


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


def _actor_id(request: FunctionCallRequest) -> int:
    raw = str(request.actor.actor_id or "").strip()
    if not raw.isdigit():
        raise SessionRelayError("actor_required", "verified numeric actor is required")
    return int(raw)


def _target_failure(request: FunctionCallRequest) -> HandlerOutcome | None:
    if request.target.kind == "global":
        return None
    return _failure("target_invalid", "relay functions require target.kind='global'")


def handle_relay_list(request: FunctionCallRequest) -> HandlerOutcome:
    """Return public relay facts visible to the authenticated operator."""
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayListRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    try:
        actor_id = _actor_id(request)
    except SessionRelayError as exc:
        return _failure(exc.code, str(exc))

    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_relay_read import list_visible_relays

    conn = connect()
    try:
        relays = list_visible_relays(
            conn,
            actor_id=actor_id,
            project=payload.project,
            state=payload.state,
            limit=payload.limit,
        )
    except (SessionRelayError, LookupError, ValueError) as exc:
        return _failure(getattr(exc, "code", "relay_list_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={"relays": relays, "count": len(relays)},
    )


def handle_relay_claim(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayClaimRequest.model_validate(request.payload or {})
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
                    actor_id=_actor_id(request),
                    machine_id=payload.machine_id,
                    hostname=payload.hostname,
                    relay_version=payload.relay_version,
                    surface_versions=payload.surfaces,
                    project_ids=payload.projects,
                ),
                wait_seconds=payload.wait_seconds,
                broker_only=payload.broker_only,
            )
        except (SessionRelayError, ValueError) as exc:
            return _failure(getattr(exc, "code", "relay_claim_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=outcome.to_dict())


def handle_relay_report(request: FunctionCallRequest) -> HandlerOutcome:
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayReportRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_relay import report_relay_job

    conn = connect()
    try:
        try:
            result = report_relay_job(
                conn,
                actor_id=_actor_id(request),
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
    "RelayClaimResponse",
    "RelayListResponse",
    "RelayReportResponse",
    "handle_relay_claim",
    "handle_relay_list",
    "handle_relay_report",
]
