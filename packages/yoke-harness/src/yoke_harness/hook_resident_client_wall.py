"""Resident handoff for client-owned hook completion timing."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from yoke_contracts.hook_evaluator_protocol import (
    HOOK_CLIENT_WALL_BATCH_FIELD,
    HookClientWallReport,
    HookEvaluatorRequest,
)
from yoke_contracts.hook_process_context import (
    HookProcessContext,
    activate_process_context,
)


@dataclass(frozen=True)
class PendingClientWall:
    observation_id: str
    endpoint: str
    authorization: str
    client_wall_ms: int
    enqueued_at: float

    batch_field = HOOK_CLIENT_WALL_BATCH_FIELD

    def payload(self) -> dict[str, Any]:
        return {
            "event_id": self.observation_id,
            "client_wall_ms": self.client_wall_ms,
        }


def record_resident_client_wall(
    *,
    queue: Any,
    request: HookEvaluatorRequest,
    report: HookClientWallReport,
    target: tuple[str, str] | None,
) -> None:
    """Validate a completion and retain or locally apply it."""
    if report.event_id != request.client_timing_id:
        return
    if target is not None:
        queue.enqueue(
            PendingClientWall(
                observation_id=report.event_id,
                endpoint=target[0],
                authorization=target[1],
                client_wall_ms=report.client_wall_ms,
                enqueued_at=time.monotonic(),
            )
        )
        return
    process = HookProcessContext(
        environment=dict(request.environment),
        cwd=request.cwd,
        pid=request.pid,
        ppid=request.ppid,
    )
    try:
        with activate_process_context(process):
            from yoke_cli.hook_client_wall import record_client_wall

            record_client_wall(report.event_id, report.client_wall_ms)
    except Exception:
        return


__all__ = ["PendingClientWall", "record_resident_client_wall"]
