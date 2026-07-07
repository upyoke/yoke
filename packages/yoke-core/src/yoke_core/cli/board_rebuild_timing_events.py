"""Timing telemetry for ``yoke board rebuild`` CLI invocations."""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from yoke_core.domain.events import emit_event


EVENT_KIND = "workflow"
EVENT_TYPE = "board_rebuild_command"
TOOL_NAME = "yoke board rebuild"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def duration_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def start_clock() -> float:
    return time.perf_counter()


def new_trace_id() -> str:
    return str(uuid.uuid4())


def ambient_session_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    for env_name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        value = os.environ.get(env_name)
        if value:
            return value
    return ""


def _board_project(repo_root: Path, conn: Any | None = None) -> str:
    from yoke_core.domain import machine_config
    from yoke_core.domain.project_identity import resolve_project_slug

    project_id = machine_config.project_id(repo_root)
    if project_id is not None:
        if conn is not None:
            try:
                return resolve_project_slug(conn, project_id)
            except Exception:
                pass
        return str(project_id)
    return "yoke"


def _event_id_from_result(result: object) -> str | None:
    event_id = getattr(result, "event_id", None)
    return event_id if isinstance(event_id, str) else None


def emit_board_command_event(
    event_name: str,
    *,
    repo_root: Path,
    board_path: Path,
    force: bool,
    output_name: str | None,
    scope: str | None,
    session_id: str,
    trace_id: str,
    started_at: str,
    completed_at: str | None = None,
    duration_ms_value: int | None = None,
    exit_code: int | None = None,
    status: str | None = None,
    changed: bool | None = None,
    message: str = "",
    targets: list[dict[str, Any]] | None = None,
    exception_type: str = "",
    phases_ms: dict[str, int] | None = None,
    print_mode: str = "",
    conn: Any | None = None,
) -> str | None:
    context: Dict[str, Any] = {
        "command": TOOL_NAME,
        "repo_root": str(repo_root),
        "board_path": str(board_path),
        "force": force,
        "output_name": output_name,
        "scope": scope,
        "print_mode": print_mode,
        "started_at": started_at,
        "pid": os.getpid(),
        "cwd": str(Path.cwd()),
    }
    if completed_at is not None:
        context["completed_at"] = completed_at
    if status is not None:
        context["status"] = status
    if changed is not None:
        context["changed"] = changed
    if message:
        context["message"] = message
    if targets is not None:
        context["targets"] = targets
    if exception_type:
        context["exception_type"] = exception_type
    if phases_ms is not None:
        context["phases_ms"] = phases_ms

    outcome = "started"
    severity = "INFO"
    if event_name.endswith("Completed"):
        outcome = "completed"
    elif event_name.endswith("Failed"):
        outcome = "failed"
        severity = "WARN"

    result = emit_event(
        event_name,
        event_kind=EVENT_KIND,
        event_type=EVENT_TYPE,
        source_type="backend",
        session_id=session_id,
        severity=severity,
        outcome=outcome,
        project=_board_project(repo_root, conn),
        tool_name=TOOL_NAME,
        duration_ms=duration_ms_value,
        trace_id=trace_id,
        exit_code=exit_code,
        context=context,
        conn=conn,
    )
    return _event_id_from_result(result)


__all__ = [
    "EVENT_KIND",
    "EVENT_TYPE",
    "TOOL_NAME",
    "ambient_session_id",
    "duration_ms",
    "emit_board_command_event",
    "new_trace_id",
    "start_clock",
    "utc_now",
]
