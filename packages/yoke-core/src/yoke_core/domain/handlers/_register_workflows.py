"""Handler registration for the workflows.* read wrappers."""

from __future__ import annotations

from yoke_core.domain.handlers import workflows_definition as _wd


def register(registry) -> None:
    registry.register(
        "workflows.definition.get", _wd.handle_workflows_definition_get,
        _wd.WorkflowsDefinitionGetRequest,
        _wd.WorkflowsDefinitionGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.workflows_definition",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
