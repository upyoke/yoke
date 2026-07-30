"""Register the internal merge-worktree finalize control-plane touches.

These two functions are the transport-aware forms of the prune authority
verdict and the post-rebase QA requirement resolution the merge engine
relays so the finalize path works over an https control plane as well as a
local Postgres connection. Both are ``adapter_status='internal'`` (merge
glue, never an agent CLI surface), so they need no CLI adapter inventory
row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import merge_engine_internal_ops as _ops


def register(registry) -> None:
    registry.register(
        "merge.prune.authority_verdict",
        _ops.handle_prune_authority_verdict,
        _ops.PruneAuthorityRequest,
        _ops.PruneAuthorityResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_engine_internal_ops",
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )
    registry.register(
        "merge.tests.post_rebase_requirement",
        _ops.handle_post_rebase_requirement,
        _ops.PostRebaseRequirementRequest,
        _ops.PostRebaseRequirementResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.merge_engine_internal_ops",
        target_kinds=["item"],
        side_effects=["qa_requirements_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


__all__ = ["register"]
