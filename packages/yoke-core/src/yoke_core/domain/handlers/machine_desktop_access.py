"""Authorize a secret-free desktop route on the machine's registered project."""

from __future__ import annotations

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_core.domain.handlers.machine_qa import TestMachineGetRequest, handle_get


class DesktopAccessResponse(BaseModel):
    project: str
    machine: str
    settings: dict[str, str]


def handle_desktop_access(request):
    outcome = handle_get(request)
    if not outcome.primary_success:
        return outcome
    detail = outcome.result_payload
    lease = detail.get("active_lease")
    if lease and lease.get("session_id") != request.actor.session_id:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code="test_machine_leased",
                message="Desktop access could disturb another session's QA run",
                recovery_hint="Wait for the registered machine lease to release or ask its holder to connect.",
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
    return HandlerOutcome(
        primary_success=True,
        result_payload={key: detail[key] for key in ("project", "machine", "settings")},
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
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["secret_values_never_returned", "registered_machine_lease"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
