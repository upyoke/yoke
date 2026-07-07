"""SubagentStop event payload and emission helpers."""

from __future__ import annotations

import json
import sys
from typing import Any

from .agent_stop_chains import StopContext


def resolve_stop_reason(ctx: StopContext) -> str:
    """Resolve the stop_reason field for HarnessSessionStopped context.

    Returns one of:
    - ``completed`` — terminal handoff state already exists (done/reviewed-implementation)
    - ``auto_committed`` — safety net committed work during stop handling
    - ``unexpected_stop`` — all other cases
    """
    if ctx.final_status in ("done", "reviewed-implementation"):
        return "completed"
    if ctx.auto_committed:
        return "auto_committed"
    return "unexpected_stop"


def build_stop_event_context(ctx: StopContext) -> str:
    """Build context JSON for HarnessSessionStopped event."""
    if not ctx.stop_reason:
        ctx.stop_reason = resolve_stop_reason(ctx)

    payload: dict[str, Any] = {
        "hook": "agent_stop",
        "auto_committed": ctx.auto_committed,
        "dispatch_type": ctx.dispatch_type,
        "stop_reason": ctx.stop_reason,
    }

    if ctx.epic_id:
        try:
            payload["epic_id"] = int(ctx.epic_id)
        except ValueError:
            payload["epic_id"] = ctx.epic_id
    if ctx.task_num:
        try:
            payload["task_num"] = int(ctx.task_num)
        except ValueError:
            payload["task_num"] = ctx.task_num
    if ctx.final_status:
        payload["final_status"] = ctx.final_status

    return json.dumps(payload, separators=(",", ":"))


def determine_stop_outcome(final_status: str) -> str:
    """Determine the event outcome based on final task status."""
    if final_status in ("done", "reviewed-implementation"):
        return "completed"
    return "stopped"


def emit_harness_session_stopped(script_dir: str, session_id: str, ctx: StopContext) -> None:
    """Emit HarnessSessionStopped via the native Python emitter."""
    del script_dir  # The native emitter resolves DB context internally.
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        try:
            context_obj = json.loads(build_stop_event_context(ctx))
        except (ValueError, TypeError):
            context_obj = {"raw": build_stop_event_context(ctx)}
        kwargs: dict = {
            "event_kind": "system",
            "event_type": "session_lifecycle",
            "source_type": "agent",
            "severity": "INFO",
            "outcome": determine_stop_outcome(ctx.final_status),
            "session_id": session_id,
            "project": "yoke",
            "context": context_obj,
        }
        if ctx.epic_id:
            kwargs["item_id"] = ctx.epic_id
        elif ctx.item_id:
            kwargs["item_id"] = ctx.item_id
        if ctx.task_num:
            try:
                kwargs["task_num"] = int(ctx.task_num)
            except (TypeError, ValueError):
                pass
        _native_emit("HarnessSessionStopped", **kwargs)
    except Exception:
        pass


def _emit_auto_commit_warning(ctx: StopContext) -> None:
    """Preserve the historical stderr contract for safety-net commits."""
    if not ctx.auto_committed:
        return
    count = ctx.auto_commit_file_count or 0
    print(
        f"Warning: Engineer left {count} uncommitted file(s) in worktree. Auto-committed as safety net.",
        file=sys.stderr,
    )
    print(f"Files: {ctx.auto_commit_files or 'unknown'}", file=sys.stderr)
    print(
        "Submission blocked: parent conduct must re-dispatch before reviewed-implementation.",
        file=sys.stderr,
    )
