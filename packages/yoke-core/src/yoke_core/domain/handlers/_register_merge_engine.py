"""Register the internal merge-worktree finalize control-plane touches.

These two functions are the transport-aware forms of the prune authority
verdict and integrated-tree verification-command resolution the merge engine
relays so the finalize path works over an https control plane as well as a
local Postgres connection. Both are ``adapter_status='internal'`` (merge glue,
never an agent CLI surface), so they need no CLI adapter inventory row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import merge_engine_internal_ops as _ops
from yoke_core.domain.handlers import merge_lock_ops as _lock

_LOCK_MODULE = "yoke_core.domain.handlers.merge_lock_ops"


def _register_lock(registry, function_id, handler, request_model, response_model):
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module=_LOCK_MODULE,
        target_kinds=["global"],
        side_effects=["db_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


def register(registry) -> None:
    _register_lock(
        registry,
        "merge.lock.list",
        _lock.handle_lock_list,
        _lock.LockListRequest,
        _lock.LockListResponse,
    )
    _register_lock(
        registry,
        "merge.lock.acquire",
        _lock.handle_lock_acquire,
        _lock.LockAcquireRequest,
        _lock.LockAcquireResponse,
    )
    _register_lock(
        registry,
        "merge.lock.release",
        _lock.handle_lock_release,
        _lock.LockReleaseRequest,
        _lock.LockReleaseResponse,
    )
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
