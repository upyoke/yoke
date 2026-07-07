"""Handler registration for hook.* operations."""

from __future__ import annotations

from yoke_core.domain.handlers import hooks as _hooks


def register(registry) -> None:
    registry.register(
        "hook.evaluate.run",
        _hooks.handle_hook_evaluate,
        _hooks.HookEvaluateRequest,
        _hooks.HookEvaluateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.hooks",
        target_kinds=["global"],
        side_effects=["hook_evaluate"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
