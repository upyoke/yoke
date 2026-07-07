"""Register onboarding checklist function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import onboard_checklist as h


def register(registry) -> None:
    # No onboarding-specific event helper exists yet; the function
    # dispatcher's YokeFunctionCalled event is the durable linkage.
    registry.register(
        "onboard.checklist.init",
        h.handle_onboard_checklist_init,
        h.OnboardChecklistInitRequest,
        h.OnboardChecklistInitResponse,
        stability="beta",
        owner_module=__name__,
        target_kinds=["system"],
        side_effects=["db_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        h.project_onboarding_runs.OPERATION_RUN,
        h.handle_onboard_checklist_run,
        h.OnboardChecklistRunRequest,
        h.OnboardChecklistRunResponse,
        stability="beta",
        owner_module=__name__,
        target_kinds=["system"],
        side_effects=["db_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
