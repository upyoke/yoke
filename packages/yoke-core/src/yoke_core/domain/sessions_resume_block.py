"""Slim resume-block renderer + CLI for the hook-runner lifecycle path.

When a session reactivates with prior session_ended claims, the
reactivation path writes ``harness_sessions.pending_resume_notice`` and
the next harness ``UserPromptSubmit`` / ``SessionStart`` for that session
renders a short block summarising what happened. The block is rendered
exactly once per reactivation cycle: the render clears the notice column
(a later reactivation re-arms it). ``HarnessSessionResumeBlockShown``
stays as the telemetry marker; it is no longer read back as state.

The renderer is split from ``sessions_lifecycle_reactivation`` so that
the auto-reacquire flow stays narrow and the renderer fits the
hook-runner subprocess shape (the only consumer today).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Optional

from .scheduler_events import emit_harness_session_resume_block_shown
from .sessions_resume_notice import (
    clear_pending_resume_notice,
    lookup_unacknowledged_resume_block,
)


def _claim_summary_line(notice: Dict[str, Any]) -> str:
    released = notice.get("released_claims") or []
    if not released:
        return "Claims at reactivation: (none recorded)"
    parts: List[str] = []
    for entry in released:
        target_kind = entry.get("target_kind", "item")
        item_id = entry.get("item_id")
        epic_id = entry.get("epic_id")
        task_num = entry.get("task_num")
        if target_kind == "epic_task" and epic_id is not None and task_num is not None:
            ref = f"YOK-{epic_id} task #{task_num}"
        elif item_id is not None:
            ref = (
                f"YOK-{item_id}"
                if not str(item_id).startswith("YOK-")
                else str(item_id)
            )
        else:
            ref = "(unknown)"
        parts.append(f"{ref} ({target_kind})")
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
    lines.extend([
        "To resume work explicitly:",
        "  /yoke do                # let the scheduler decide",
        "  python3 -m yoke_core.api.service_client claim-work --item YOK-N",
    ])
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


def _main(argv: Optional[List[str]] = None) -> int:
    argv = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="sessions-resume-block")
    parser.add_argument("--session-id", required=True)
    parser.add_argument(
        "--harness-event", required=True,
        choices=("UserPromptSubmit", "SessionStart"),
    )
    parsed = parser.parse_args(argv)

    from .db_helpers import connect

    # Postgres authority resolves the DSN; the backend factory configures the
    # row factory, so no file path is constructed here.
    try:
        conn = connect()
    except Exception:
        return 0
    try:
        block = render_and_mark(
            conn, parsed.session_id, harness_event=parsed.harness_event,
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass
    if block:
        sys.stdout.write(block)
    return 0


__all__ = [
    "render_and_mark",
    "render_resume_block_lines",
]


if __name__ == "__main__":
    sys.exit(_main())
