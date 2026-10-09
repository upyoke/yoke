"""Authorize a secret-free desktop route on the machine's registered project."""

from __future__ import annotations

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import TestMachineGetRequest, handle_get
from yoke_core.domain import actors, db_helpers
from yoke_core.domain.auth_context import auth_context_from_actor
from yoke_core.domain.events import emit_event
from yoke_core.domain.session_less_actor_binding import bind_operating_actor
from yoke_core.domain.session_action_attribution import EVENT_SESSION_ACTION_PERFORMED


class DesktopAccessResponse(BaseModel):
    project: str
    machine: str
    settings: dict[str, str]
    operator_access: dict | None = None


def handle_desktop_access(request):
    outcome = handle_get(request)
    if not outcome.primary_success:
        return outcome
    detail = outcome.result_payload
    lease = detail.get("active_lease")
    operator_access = None
    if (
        lease
        and lease.get("session_id") != request.actor.session_id
        and request.actor.session_id
    ):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="test_machine_leased",
                message="Desktop access could disturb another session's QA run",
                recovery_hint="Wait for the lease holder to finish. A human can assist from a plain terminal with yoke test-machine desktop-access --project P --machine NAME --view.",
            ),
        )
    if not detail["settings"].get("desktop_route"):
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="desktop_route_missing",
                message="This test machine has no desktop route",
                recovery_hint="Declare desktop_route, desktop_protocol, desktop_port and desktop_user with yoke test-machine settings-replace.",
            ),
        )
    if lease and not request.actor.session_id:
        request = bind_operating_actor(request)
        conn = db_helpers.connect()
        try:
            actor_id = request.actor.actor_id
            numeric_actor = int(actor_id) if str(actor_id or "").isdigit() else None
            if numeric_actor is None or not actors.is_human_actor(conn, numeric_actor):
                return HandlerOutcome(
                    primary_success=False,
                    error=FunctionError(
                        code="desktop_operator_identity_required",
                        message="Assisting a leased desktop requires an authenticated human operator",
                        recovery_hint="Sign in as a human operator and rerun desktop-access from a plain terminal outside a harness session.",
                    ),
                )
            operator_access = {
                "actor_id": str(actor_id),
                "actor_name": actors.actor_name(conn, numeric_actor),
                "lease_id": lease["id"],
                "holder_session_id": lease["session_id"],
                "lease_unchanged": True,
            }
            audit = emit_event(
                EVENT_SESSION_ACTION_PERFORMED,
                event_kind="lifecycle",
                event_type="session_action",
                source_type="api",
                session_id=lease["session_id"],
                project=detail["project"],
                request_id=request.request_id,
                auth_context=auth_context_from_actor(actor_id),
                context={
                    "action": "desktop access authorized",
                    "function": request.function,
                    **operator_access,
                },
                conn=conn,
            )
            operator_access["audit_recorded"] = audit.ok
            if not audit.ok:
                operator_access["audit_recovery"] = (
                    f"desktop_access_audit_unavailable: {audit.reason}; "
                    "ask the control-plane operator to repair event capture"
                )
        finally:
            conn.close()
    result = {key: detail[key] for key in ("project", "machine", "settings")}
    if operator_access is not None:
        result["operator_access"] = operator_access
    return HandlerOutcome(
        primary_success=True,
        result_payload=result,
    )


def register(registry):
    registry.register(
        "test_machine.desktop_access",
        handle_desktop_access,
        TestMachineGetRequest,
        DesktopAccessResponse,
        stability="stable",
        minimum_serving_version="next-release",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled", EVENT_SESSION_ACTION_PERFORMED],
        guardrails=["secret_values_never_returned", "registered_machine_lease"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
