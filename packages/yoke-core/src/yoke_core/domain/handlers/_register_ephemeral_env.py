"""Register ephemeral environment function handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import ephemeral_env as _handlers


def register(registry) -> None:
    registry.register(
        "ephemeral_env.update",
        _handlers.handle_ephemeral_env_update,
        _handlers.EphemeralEnvUpdateRequest,
        _handlers.EphemeralEnvUpdateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.ephemeral_env",
        target_kinds=["global"],
        side_effects=["ephemeral_environments_update"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )


__all__ = ["register"]
