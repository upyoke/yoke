"""Domain-owned interfaces supplied by the installed execution engines.

Each port resolves through the standard runtime loader, retaining the engine module
and its exception identities. Missing or mismatched installations refuse with recovery.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class MainCheckoutSync(Protocol):
    """Execution operations required by domain callers of main_checkout_sync."""

    fast_forward_main_checkout: Callable[..., Any]


def get_main_checkout_sync() -> MainCheckoutSync:
    return cast(MainCheckoutSync, load_port("main_checkout_sync", MainCheckoutSync))


class RunsContinueForItem(Protocol):
    """Execution operations required by domain callers of runs_continue_for_item."""

    continue_for_item: Callable[..., Any]
    OUTCOME_BOUND: str
    OUTCOME_NONE: str
    OUTCOME_PINNED: str
    OUTCOME_WAITING: str


def get_runs_continue_for_item() -> RunsContinueForItem:
    return cast(RunsContinueForItem, load_port("runs_continue_for_item", RunsContinueForItem))


class LaneBaseUpdate(Protocol):
    """Execution operations required by domain callers of lane_base_update."""

    bring_lane_current: Callable[..., Any]
    merge_context: Callable[..., Any]
    LaneBaseUpdateRefused: type[Exception]


def get_lane_base_update() -> LaneBaseUpdate:
    return cast(LaneBaseUpdate, load_port("lane_base_update", LaneBaseUpdate))


class DoneTransitionGates(Protocol):
    """Execution operations required by domain callers of done_transition_gates."""

    _get_base_branch: Callable[..., Any]
    _resolve_default_branch: Callable[..., Any]


def get_done_transition_gates() -> DoneTransitionGates:
    return cast(DoneTransitionGates, load_port("done_transition_gates", DoneTransitionGates))


class DeployRunWorktreeNaming(Protocol):
    """Execution operations required by domain callers of deploy_run_worktree_naming."""

    driver_worktree_path: Callable[..., Any]


def get_deploy_run_worktree_naming() -> DeployRunWorktreeNaming:
    return cast(DeployRunWorktreeNaming, load_port("deploy_run_worktree_naming", DeployRunWorktreeNaming))


class DeployRunWorktreeRetirement(Protocol):
    """Execution operations required by domain callers of deploy_run_worktree_retirement."""

    retire_terminal_deploy_run_worktrees: Callable[..., Any]


def get_deploy_run_worktree_retirement() -> DeployRunWorktreeRetirement:
    return cast(DeployRunWorktreeRetirement, load_port("deploy_run_worktree_retirement", DeployRunWorktreeRetirement))


class RunsStartForItem(Protocol):
    """Execution operations required by domain callers of runs_start_for_item."""

    start_for_item: Callable[..., Any]


def get_runs_start_for_item() -> RunsStartForItem:
    return cast(RunsStartForItem, load_port("runs_start_for_item", RunsStartForItem))


class StandaloneItemMergeEngine(Protocol):
    """Execution operations required by domain callers of standalone_item_merge_engine."""

    run: Callable[..., Any]


def get_standalone_item_merge_engine() -> StandaloneItemMergeEngine:
    return cast(StandaloneItemMergeEngine, load_port("standalone_item_merge_engine", StandaloneItemMergeEngine))


class TerminalLaneCleanup(Protocol):
    """Execution operations required by domain callers of terminal_lane_cleanup."""

    record_terminal_lane_close_out: Callable[..., Any]


def get_terminal_lane_cleanup() -> TerminalLaneCleanup:
    return cast(TerminalLaneCleanup, load_port("terminal_lane_cleanup", TerminalLaneCleanup))


class DoneTransitionRunner(Protocol):
    """Execution operations required by domain callers of done_transition_runner."""

    run: Callable[..., Any]


def get_done_transition_runner() -> DoneTransitionRunner:
    return cast(DoneTransitionRunner, load_port("done_transition_runner", DoneTransitionRunner))


class WorktreeMaintenance(Protocol):
    """Execution operations required by domain callers of worktree_maintenance."""

    retire_finished_lanes: Callable[..., Any]


def get_worktree_maintenance() -> WorktreeMaintenance:
    return cast(WorktreeMaintenance, load_port("worktree_maintenance", WorktreeMaintenance))


class MigrationMergePreflight(Protocol):
    """Execution operations required by domain callers of migration_merge_preflight."""

    lane_only_migration_entries: Callable[..., Any]


def get_migration_merge_preflight() -> MigrationMergePreflight:
    return cast(MigrationMergePreflight, load_port("migration_merge_preflight", MigrationMergePreflight))
