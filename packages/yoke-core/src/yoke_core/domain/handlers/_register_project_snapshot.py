"""Register project path-snapshot sync handlers."""

from __future__ import annotations

from yoke_core.domain.handlers import project_snapshot_ensure_at as ensure_at
from yoke_core.domain.handlers import project_snapshot_sync as h


def register(registry) -> None:
    registry.register(
        "project.snapshot.sync",
        h.handle_project_snapshot_sync,
        h.ProjectSnapshotSyncRequest,
        h.ProjectSnapshotSyncResponse,
        stability="beta",
        owner_module="yoke_core.domain.handlers.project_snapshot_sync",
        target_kinds=["global"],
        side_effects=["path_snapshot_write", "path_target_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "project.snapshot.ensure_at",
        ensure_at.handle_project_snapshot_ensure_at,
        ensure_at.ProjectSnapshotEnsureAtRequest,
        ensure_at.ProjectSnapshotEnsureAtResponse,
        stability="beta",
        owner_module="yoke_core.domain.handlers.project_snapshot_ensure_at",
        target_kinds=["global"],
        side_effects=["path_snapshot_write", "path_target_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        # Engine-relayed glue (post-merge / hook snapshot pre-warm), never an
        # agent CLI surface, so it carries no CLI adapter inventory row.
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
