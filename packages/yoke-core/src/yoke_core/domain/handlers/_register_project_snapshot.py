"""Register project path-snapshot sync handlers."""

from __future__ import annotations

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


__all__ = ["register"]
