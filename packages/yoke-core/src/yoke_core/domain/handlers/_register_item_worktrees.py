"""Register public item-worktree lane reads and recovery release."""

from __future__ import annotations

from yoke_core.domain.handlers import item_worktrees as _item_worktrees


def register(registry) -> None:
    registry.register(
        "item_worktrees.get",
        _item_worktrees.handle_get,
        _item_worktrees.ItemWorktreesGetRequest,
        _item_worktrees.ItemWorktreesGetResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktrees",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "item_worktrees.release",
        _item_worktrees.handle_release,
        _item_worktrees.ItemWorktreesReleaseRequest,
        _item_worktrees.ItemWorktreesReleaseResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktrees",
        target_kinds=["item"],
        side_effects=["item_worktrees_update_state"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "actor_holds_item_claim",
            "evidence_only_status",
            "single_implementation_lane",
            "clean_lane_attestation",
        ],
        adapter_status="live",
        claim_required_kind="item",
    )


__all__ = ["register"]
