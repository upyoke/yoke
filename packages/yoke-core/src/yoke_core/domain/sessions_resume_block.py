"""Slim resume-block renderer for the hook-runner lifecycle path.

When a session reactivates with prior session_ended claims, the
reactivation path writes ``harness_sessions.pending_resume_notice`` and
the next harness ``UserPromptSubmit`` / ``SessionStart`` for that session
renders a short block summarising what happened. The block is rendered
exactly once per reactivation cycle: the render clears the notice column
(a later reactivation re-arms it). ``HarnessSessionResumeBlockShown``
stays as the telemetry marker; it is no longer read back as state.

The renderer is split from ``sessions_lifecycle_reactivation`` so that
the auto-reacquire flow stays narrow; its one consumer is the
``yoke_core.hooks.session_resume_block`` chain policy.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .scheduler_events import emit_harness_session_resume_block_shown
from .sessions_resume_notice import (
    clear_pending_resume_notice,
    lookup_unacknowledged_resume_block,
)
from .work_claim_targets import from_row as target_from_row


def _claim_summary_line(notice: Dict[str, Any]) -> str:
    released = notice.get("released_claims") or []
    if not released:
        return "Claims at reactivation: (none recorded)"
    parts: List[str] = []
    for entry in released:
        target = target_from_row(entry)
        parts.append(f"{target.render()} ({target.kind})")
    return "Claims at reactivation: " + ", ".join(parts)


def _reacquire_outcome_lines(notice: Dict[str, Any]) -> List[str]:
    reacquired = int(notice.get("reacquired_count") or 0)
    conflict = int(notice.get("conflict_count") or 0)
    if reacquired == 0 and conflict == 0:
        return []
    parts: List[str] = []
    if reacquired:
        parts.append(f"{reacquired} auto-reacquired")
    if conflict:
        parts.append(f"{conflict} NOT auto-reacquired (in-conflict)")
    return ["Outcome: " + " | ".join(parts)]


def render_resume_block_lines(notice: Dict[str, Any]) -> List[str]:
    """Compose the slim 5-8 line resume block content (no leading '> ')."""
    lines = [
        "**SESSION RESUMED.** Your session was ended (likely by a stop/SessionEnd "
        "hook) and reactivated.",
        _claim_summary_line(notice),
    ]
    lines.extend(_reacquire_outcome_lines(notice))
    lines.extend(
        [
            "To resume work explicitly:",
            "  /yoke charge            # select a runnable item",
            '  yoke claims work acquire --item YOK-N --reason "<intent>"',
        ]
    )
    return lines


def render_and_mark(
    conn: Any,
    session_id: str,
    *,
    harness_event: str,
) -> str:
    """Render the slim resume block once per reactivation cycle."""
    notice = lookup_unacknowledged_resume_block(conn, session_id)
    if notice is None:
        return ""
    lines = render_resume_block_lines(notice)
    block = "\n".join(f"> {line}" for line in lines) + "\n"
    reacquired = int(notice.get("reacquired_count") or 0) > 0
    clear_pending_resume_notice(conn, session_id)
    emit_harness_session_resume_block_shown(
        session_id=session_id,
        harness_event=harness_event,
        reactivation_event_id=None,
        reacquired=reacquired,
        advisory_only=not reacquired,
    )
    return block


__all__ = [
    "render_and_mark",
    "render_resume_block_lines",
]
