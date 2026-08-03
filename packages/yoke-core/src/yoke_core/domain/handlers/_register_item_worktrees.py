"""Register public item-worktree lane creation, reads, and recovery."""

from __future__ import annotations

from yoke_core.domain.handlers import item_worktree_create as _item_worktree_create
from yoke_core.domain.handlers import item_worktree_paths as _item_worktree_paths
from yoke_core.domain.handlers import item_worktrees as _item_worktrees


def register(registry) -> None:
    registry.register(
        "item_worktrees.create",
        _item_worktree_create.handle_create,
        _item_worktree_create.ItemWorktreesCreateRequest,
        _item_worktree_create.ItemWorktreesCreateResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktree_create",
        target_kinds=["item"],
        side_effects=["item_worktrees_insert"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "actor_holds_item_claim",
            "active_item",
            "pinned_workflow_lane_policy",
            "default_or_explicit_lane",
            "sole_required_first_lane",
            "path_claim_gate",
            "unique_active_project_branch",
            "single_integration_lane",
        ],
        adapter_status="live",
        claim_required_kind="item",
    )
    registry.register(
        "item_worktrees.list",
        _item_worktree_paths.handle_list,
        _item_worktree_paths.ItemWorktreesListRequest,
        _item_worktree_paths.ItemWorktreesListResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktree_paths",
        target_kinds=["item"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
    )
    registry.register(
        "item_worktrees.path_record",
        _item_worktree_paths.handle_path_record,
        _item_worktree_paths.ItemWorktreePathRecordRequest,
        _item_worktree_paths.ItemWorktreePathRecordResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktree_paths",
        target_kinds=["item"],
        side_effects=["item_worktrees_update_path"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[
            "actor_holds_item_claim",
            "active_item",
            "active_lane_id_precondition",
            "unchanged_branch_precondition",
            "unique_active_path",
        ],
        adapter_status="live",
        claim_required_kind="item",
    )
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
    registry.register(
        "item_worktrees.release_merged_lane",
        _item_worktrees.handle_release_merged_lane,
        _item_worktrees.ItemWorktreesReleaseMergedLaneRequest,
        _item_worktrees.ItemWorktreesReleaseMergedLaneResponse,
        stability="stable",
        owner_module="yoke_core.domain.handlers.item_worktrees",
        target_kinds=["item"],
        side_effects=["item_worktrees_update_state"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["actor_holds_item_claim"],
        # No CLI adapter by design: the merge engine is the only caller, and
        # it invokes this in the same act that removes the lane directory.
        adapter_status="internal",
        claim_required_kind="item",
    )


__all__ = ["register"]
