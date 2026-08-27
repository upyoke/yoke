"""Register the internal done-transition finalize writes.

These internal write functions carry done-transition finalization and the
merge-queue handoff over an https control plane as well as local Postgres.
They are ``adapter_status='internal'`` (merge finalize glue,
never an agent CLI surface), so they need no CLI adapter row, and they are
``ambient_session_required=False`` because the done transition runs in a
merge subprocess that may resolve no ambient harness session — matching
the no-session posture of the done-transition read siblings. They are
claim-free because the merge writes they replace opened a raw
control-plane connection with no claim check; the item-claim / QA-gate
ceremony is enforced by the upstream status flip, not by these finalize
writes.
"""

from __future__ import annotations

from yoke_core.domain.handlers import done_transition_writes as _writes

_MODULE = "yoke_core.domain.handlers.done_transition_writes"


def register(registry) -> None:
    registry.register(
        "done_transition.finalize_local_side_effects",
        _writes.handle_finalize_local_side_effects,
        _writes.FinalizeLocalSideEffectsRequest,
        _writes.FinalizeLocalSideEffectsResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_deployed_to_write", "release_entry_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "done_transition.populate_merged_at",
        _writes.handle_populate_merged_at,
        _writes.PopulateMergedAtRequest,
        _writes.PopulateMergedAtResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_merged_at_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "merge_queue.landing_pending.mark",
        _writes.handle_mark_landing_pending,
        _writes.MarkLandingPendingRequest,
        _writes.MarkLandingPendingResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_merge_queue_marker_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "merge_queue.landing_pending.clear",
        _writes.handle_clear_landing_pending,
        _writes.ClearLandingPendingRequest,
        _writes.ClearLandingPendingResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_merge_queue_marker_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
