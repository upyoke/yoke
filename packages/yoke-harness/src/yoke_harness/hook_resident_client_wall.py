"""Resident handoff for client-owned hook completion timing."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Any

from yoke_contracts.hook_evaluator_protocol import (
    HOOK_CLIENT_WALL_BATCH_FIELD,
    HookClientWallReport,
    HookEvaluatorProtocolError,
    HookEvaluatorRequest,
    receive_frame,
    send_frame,
)
from yoke_contracts.hook_resident_routing import message_probe_key
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
    session_key: str

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
    process = HookProcessContext(
        environment=dict(request.environment),
        cwd=request.cwd,
        pid=request.pid,
        ppid=request.ppid,
    )
    try:
        with activate_process_context(process):
            from yoke_contracts.hook_runner.folder_scope import folder_scope

            # Completion arrives after evaluation, independently of its
            # on_complete callback. Keep that frame inside the same boundary.
            if folder_scope(request.stdin) != "registered":
                return
            if target is not None:
                queue.enqueue(
                    PendingClientWall(
                        observation_id=report.event_id,
                        endpoint=target[0],
                        authorization=target[1],
                        client_wall_ms=report.client_wall_ms,
                        enqueued_at=time.monotonic(),
                        session_key=message_probe_key(request.stdin),
                    )
                )
                return
            from yoke_cli.hook_client_wall import record_client_wall

            record_client_wall(report.event_id, report.client_wall_ms)
    except Exception:
        return


def reply_with_client_wall(
    peer: Any,
    response: dict[str, Any],
    request: HookEvaluatorRequest | None,
    queue: Any,
    target: tuple[str, str] | None,
) -> None:
    """Send the evaluated result, then collect its optional timing frame."""
    timing_id = (
        request.client_timing_id
        if request is not None and response.get("status") == "ok"
        else ""
    )
    if target is not None and timing_id:
        queue.expect_client_wall(timing_id, message_probe_key(request.stdin))
    try:
        send_frame(peer, response)
        if timing_id:
            peer.settimeout(0.25)
            report = HookClientWallReport.from_mapping(receive_frame(peer))
            record_resident_client_wall(
                queue=queue, request=request, report=report, target=target
            )
    except (HookEvaluatorProtocolError, OSError, socket.timeout):
        return
    finally:
        if target is not None and timing_id:
            queue.finish_client_wall(timing_id)


__all__ = ["PendingClientWall", "record_resident_client_wall", "reply_with_client_wall"]
