"""Registered handler for a machine relay's idle native-host report."""

from __future__ import annotations

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.session_control.models import RelayIdleHostsRequest
from yoke_core.domain.handlers.session_relay import (
    _actor_id,
    _failure,
    _target_failure,
)
from yoke_core.domain.session_relay_types import SessionRelayError


def handle_relay_idle_hosts(request: FunctionCallRequest) -> HandlerOutcome:
    """Say which idle hosts' sessions have ended; record the hosts reclaimed."""
    if invalid := _target_failure(request):
        return invalid
    try:
        payload = RelayIdleHostsRequest.model_validate(request.payload or {})
    except Exception as exc:
        return _failure("payload_invalid", str(exc))
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.session_idle_host_report import apply_idle_host_report
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
            outcome = apply_idle_host_report(
                conn,
                machine_id=payload.machine_id,
                authorized_projects=payload.projects,
                hosts=[host.model_dump(mode="json") for host in payload.hosts],
                reclaimed=[
                    entry.model_dump(mode="json") for entry in payload.reclaimed
                ],
            )
            conn.commit()
        except (SessionRelayError, ValueError) as exc:
            conn.rollback()
            return _failure(getattr(exc, "code", "relay_idle_hosts_failed"), str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=outcome)


__all__ = ["handle_relay_idle_hosts"]
