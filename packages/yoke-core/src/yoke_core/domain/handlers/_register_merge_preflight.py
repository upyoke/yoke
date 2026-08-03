"""Register the internal merge-worktree preparation preflight reads.

These three ``merge.preflight.*`` functions are pure control-plane reads the
transport-aware merge preflight relays to so its refusal gates run over an
https control plane as well as a local Postgres connection. They are
``adapter_status='internal'`` (preflight glue, never an agent CLI surface),
so they need no CLI adapter inventory row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import merge_preflight_gate_evals as _mpg


def register(registry) -> None:
    registry.register(
        "merge.preflight.epic_task_statuses",
        _mpg.handle_epic_task_statuses,
        _mpg.EpicTaskStatusesRequest,
        _mpg.EpicTaskStatusesResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_preflight_gate_evals",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "merge.preflight.dependency_gate",
        _mpg.handle_dependency_gate,
        _mpg.DependencyGateRequest,
        _mpg.DependencyGateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_preflight_gate_evals",
        target_kinds=["item", "global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "merge.preflight.blocked_gate",
        _mpg.handle_blocked_gate,
        _mpg.BlockedGateRequest,
        _mpg.BlockedGateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_preflight_gate_evals",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


__all__ = ["register"]
