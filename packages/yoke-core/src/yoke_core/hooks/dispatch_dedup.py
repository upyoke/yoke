"""Collapse a lifecycle hook dispatch the harness fired more than once.

Claude Desktop drives some lifecycle hooks from two driver processes: one
"New" click produced two ``SessionStart``, two ``UserPromptSubmit`` and two
``Stop`` dispatches from different pids while the project settings declared
one command per event. Running the chain twice re-registers the session,
re-renders the orientation block, and doubles every lifecycle side effect
behind it.

Only lifecycle events collapse. A tool event carries its own
``tool_use_id`` and must run its own guardrails: two ``PreToolUse``
dispatches mean two tool calls to police, never one dispatched twice, so
deduplicating them would drop a guardrail evaluation entirely.

Two dispatches are the same dispatch when they name the same session and
event and carry byte-identical payloads within
:data:`DISPATCH_DEDUP_WINDOW_SECONDS`. The marker proving it lives in the
machine's hook-marker directory because the duplicate arrives in a
different process; the run half keeps the relay's client-side subset run,
the server's own run, and an in-process local run from reading each other's
marker.
"""

from __future__ import annotations

import hashlib
import os
import time
from typing import Any, Optional

from yoke_core.domain.project_scratch_dir import hook_marker_path


__all__ = [
    "DEDUPLICATED_LIFECYCLE_EVENTS",
    "DISPATCH_DEDUP_WINDOW_SECONDS",
    "deduplicated_dispatch",
    "duplicate_lifecycle_dispatch",
    "emit_hook_dispatch_deduplicated",
]


#: How close together two identical dispatches must arrive to be read as one
#: dispatch the harness delivered twice rather than two real events.
DISPATCH_DEDUP_WINDOW_SECONDS = 1.0

#: The lifecycle events a harness may deliver more than once for a single
#: occurrence. Tool events are deliberately absent — see the module docstring.
DEDUPLICATED_LIFECYCLE_EVENTS = frozenset(
    {"SessionStart", "UserPromptSubmit", "Stop", "SessionEnd"}
)


def _run_half(controls: Optional[Any]) -> str:
    """Name which half of a possibly relay-split run this is.

    The relay evaluates one hook event twice on purpose — the server runs
    the registered chain, the client runs its local-state subset — so the
    two must never be read as a duplicate of each other.
    """
    if controls is None:
        return "local"
    if getattr(controls, "remote", False):
        return "server"
    return "local" if getattr(controls, "flush_tail", True) else "client"


def _payload_digest(stdin_data: str) -> str:
    return hashlib.sha256(stdin_data.encode("utf-8", "surrogatepass")).hexdigest()


def duplicate_lifecycle_dispatch(
    event_name: str,
    *,
    session_id: str,
    stdin_data: str,
    run_half: str,
) -> bool:
    """Return whether this dispatch repeats one already taken for the session.

    Claims the dispatch for this process when it does not. Any filesystem
    failure returns ``False``: an unreadable marker must let the dispatch
    through, because suppressing a lifecycle event the harness fired once is
    far worse than running one it fired twice.
    """
    if event_name not in DEDUPLICATED_LIFECYCLE_EVENTS or not session_id:
        return False
    digest = _payload_digest(stdin_data)
    try:
        marker = hook_marker_path(f"dispatch-{run_half}-{event_name}-{session_id}")
    except OSError:
        return False
    try:
        handle = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    except OSError:
        return False
    else:
        # First dispatch for this session and event: claim it atomically, so
        # a duplicate racing this process finds the marker rather than a gap.
        with os.fdopen(handle, "w", encoding="utf-8") as claimed:
            claimed.write(digest)
        return False
    try:
        previous = marker.read_text(encoding="utf-8").strip()
        age_seconds = time.time() - marker.stat().st_mtime
    except OSError:
        return False
    if previous == digest and age_seconds <= DISPATCH_DEDUP_WINDOW_SECONDS:
        return True
    try:
        marker.write_text(digest, encoding="utf-8")
    except OSError:
        return False
    return False


def emit_hook_dispatch_deduplicated(
    *,
    event_name: str,
    session_id: str,
    executor: str,
    run_half: str,
) -> None:
    """Record the collapsed dispatch. Best-effort, like all hook telemetry."""
    try:
        from yoke_core.domain.events import emit_event

        emit_event(
            "HookDispatchDeduplicated",
            event_kind="system",
            event_type="hook_dispatch",
            source_type="hook",
            session_id=session_id,
            severity="INFO",
            outcome="skipped",
            project="yoke",
            hook_event_name=event_name,
            context={
                "hook_event": event_name,
                "executor": executor,
                "run_half": run_half,
                "window_seconds": DISPATCH_DEDUP_WINDOW_SECONDS,
            },
        )
    except Exception:
        return


def deduplicated_dispatch(
    event_name: str,
    *,
    context: Any,
    stdin_data: str,
    controls: Optional[Any],
) -> bool:
    """Return whether the runner should no-op this repeated lifecycle dispatch."""
    run_half = _run_half(controls)
    session_id = str(getattr(context, "session_id", "") or "")
    if not duplicate_lifecycle_dispatch(
        event_name,
        session_id=session_id,
        stdin_data=stdin_data,
        run_half=run_half,
    ):
        return False
    if controls is None or getattr(controls, "flush_tail", True):
        # The half that owns the telemetry tail owns this row too: the
        # relay's client-side subset has no control-plane connection of its
        # own, and the server's run records the event for that dispatch.
        emit_hook_dispatch_deduplicated(
            event_name=event_name,
            session_id=session_id,
            executor=str(getattr(context, "executor_family", "") or ""),
            run_half=run_half,
        )
    return True
