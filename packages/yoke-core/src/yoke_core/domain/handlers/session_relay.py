"""Registered-function handlers for authenticated machine-relay polling."""

from __future__ import annotations

import logging

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.session_control.native_turn_end import RelayTurnEndRequest
from yoke_contracts.session_control.models import (
    RelayClaimRequest,
    RelayClaimResponse,
    RelayListRequest,
    RelayListResponse,
    RelayLivenessRequest,
    RelayLivenessResponse,
    RelayReportRequest,
    RelayReportResponse,
)
from yoke_core.domain.session_relay_types import (
    RelayHeartbeat,
    SessionRelayError,
)


_LOGGER = logging.getLogger(__name__)


def _sweep_quiet_claim_holders(conn, *, machine_id: str, projects) -> None:
    """Probe this machine's silent claim-holders.

    The probe is best-effort around the poll it rides on. The poll's job
    is to hand this relay its next wake; a probe that fails must not take
    that away, so failure is logged and the poll continues — the next poll
    tries again from the same durable rows.
    """
    from yoke_core.domain.session_stale_alive_probe import probe_stale_alive_sessions

    try:
        probe_stale_alive_sessions(
            conn, machine_id=machine_id, authorized_projects=projects
        )
    except Exception:
        _LOGGER.debug(
            "quiet claim-holder probe failed during relay poll", exc_info=True
        )


def _stuck_native_turn_probes(conn, *, machine_id: str, projects) -> list:
    """Name the sessions this machine should read a turn record back for.

    Best-effort like the sweeps above: a poll whose job is to hand the relay
    its next wake must not be lost to the probe list that would have fixed a
    later one. The next poll re-derives the same targets from the same rows.
    """
    from yoke_core.domain.session_native_turn_end import probe_targets

    try:
        return probe_targets(conn, machine_id=machine_id, authorized_projects=projects)
    except Exception:
        _LOGGER.debug("native turn-end probe targets skipped", exc_info=True)
        return []


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
    from yoke_core.domain.session_relay_authorization import (
        require_relay_project_authority,
    )

    conn = connect()
    try:
        try:
            actor_id = _actor_id(request)
            require_relay_project_authority(
                conn,
                actor_id=actor_id,
                project_ids=payload.projects,
            )
            # The poll is the only thing this machine does on a schedule, so
            # it is where the quiet-claim-holder sweeps live. Neither may
            # cost the relay its job: a poll that returns no work because a
            # sweep raised is a relay that stops waking anything at all.
            _sweep_quiet_claim_holders(
                conn,
                machine_id=payload.machine_id,
                projects=payload.projects,
            )
            outcome = claim_relay_job(
                conn,
                RelayHeartbeat(
                    relay_id=payload.relay_id,
                    actor_id=actor_id,
                    machine_id=payload.machine_id,
                    hostname=payload.hostname,
                    relay_version=payload.relay_version,
                    surface_versions=payload.surfaces,
                    project_ids=payload.projects,
                    surface_plan_limits=payload.plan_limits,
                ),
                wait_seconds=payload.wait_seconds,
                broker_only=payload.broker_only,
                broker_lease_id=payload.broker_lease_id,
                broker_session_id=(
                    str(request.actor.session_id or "").strip()
                    if payload.broker_only
                    else None
                ),
            )
            probes = _stuck_native_turn_probes(
                conn,
                machine_id=payload.machine_id,
                projects=payload.projects,
            )
        except (SessionRelayError, ValueError) as exc:
            return _failure(getattr(exc, "code", "relay_claim_failed"), str(exc))
    finally:
        conn.close()
    result = outcome.to_dict()
    result["turn_end_probes"] = probes
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_relay_turn_end(request: FunctionCallRequest) -> HandlerOutcome:
    """Reclassify the reported sessions whose native turn already ended."""
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayTurnEndRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_native_turn_end import apply_native_turn_ends
    from yoke_core.domain.session_relay_authorization import (
        require_relay_project_authority,
    )

    conn = connect()
    try:
        try:
            require_relay_project_authority(
                conn,
                actor_id=_actor_id(request),
                project_ids=payload.projects,
            )
            outcome = apply_native_turn_ends(
                conn,
                machine_id=payload.machine_id,
                authorized_projects=payload.projects,
                reports=[entry.model_dump(mode="json") for entry in payload.turn_ends],
            )
            conn.commit()
        except (SessionRelayError, ValueError) as exc:
            conn.rollback()
            return _failure(getattr(exc, "code", "relay_turn_end_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=outcome)


def handle_relay_liveness(request: FunctionCallRequest) -> HandlerOutcome:
    """Apply reports whose native process this machine proved gone."""
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayLivenessRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_process_liveness_report import (
        apply_verified_process_death_reports,
    )
    from yoke_core.domain.session_relay_authorization import (
        require_relay_project_authority,
    )

    conn = connect()
    try:
        try:
            actor_id = _actor_id(request)
            require_relay_project_authority(
                conn,
                actor_id=actor_id,
                project_ids=payload.projects,
            )
            outcome = apply_verified_process_death_reports(
                conn,
                machine_id=payload.machine_id,
                authorized_projects=payload.projects,
                reports=[report.model_dump(mode="json") for report in payload.sessions],
            )
            conn.commit()
        except (SessionRelayError, ValueError) as exc:
            conn.rollback()
            return _failure(getattr(exc, "code", "relay_liveness_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=outcome)


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
                document=(
                    payload.document.model_dump(mode="json")
                    if payload.document is not None
                    else None
                ),
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
    "RelayLivenessResponse",
    "RelayReportResponse",
    "handle_relay_claim",
    "handle_relay_list",
    "handle_relay_liveness",
    "handle_relay_report",
]
