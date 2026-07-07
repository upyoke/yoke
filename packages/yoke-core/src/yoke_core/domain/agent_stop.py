"""SubagentStop hook CLI front door.

Historical note: an earlier version of this module supported a ``--role``
flag that activated a role-aware output gate (engineer = submission-receipt
present; tester = qa_runs review row present). The gate refused subagent
termination on miss via Claude's ``{"decision":"block","reason":"..."}``
wire shape. The binding the gate relied on (`(parent session_id,
CLAUDE_PROJECT_DIR)` → `(epic_id, task_num)`) couldn't be satisfied for
subagents — they inherit the parent's CLAUDE_PROJECT_DIR (always the main
repo root), never a worktree — so the resolver returned ``None`` for every
real-world dispatch and the conservative-block path refused every
termination. The user-facing failure mode the gate aimed at (Tester emits
text VERDICT but skips ``epic review-insert``) is caught by the conduct
closeout flow, which is the load-bearing layer on both Claude and Codex.
This module now only handles the issue-flow auto-commit on SubagentStop and
emits the ``HarnessSessionStopped`` event.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

from . import agent_stop_chains as _chains
from .agent_stop_chains import StopContext
from .agent_stop_commit import BUSY_TIMEOUT_MS, AutoCommitResult, auto_commit_worktree
from .agent_stop_events import (
    _emit_auto_commit_warning,
    build_stop_event_context,
    determine_stop_outcome,
    emit_harness_session_stopped,
    resolve_stop_reason,
)


def process_dispatch_chains(*args, **kwargs):
    """Forward to :mod:`agent_stop_chains`. Kept as a re-export so existing
    imports of ``agent_stop.process_dispatch_chains`` continue to work."""
    return _chains.process_dispatch_chains(*args, **kwargs)


def _read_session_id_from_hook_stdin() -> str:
    """Read ``session_id`` from the Claude-Code SubagentStop hook stdin JSON.

    Claude Code passes a JSON object on stdin with a ``session_id`` field
    naming the parent conduct session.  Subagent hook subprocesses do not
    inherit ``YOKE_SESSION_ID`` from the parent's env, so without this
    fallback the env-var-only ``get_session_id()`` returns "unknown" and
    the event emitter records the wrong session.
    """
    try:
        if sys.stdin.isatty():  # pragma: no cover - defensive
            return ""
        payload = sys.stdin.read()
    except (OSError, ValueError):
        return ""
    if not payload.strip():
        return ""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    raw = data.get("session_id")
    if not isinstance(raw, str):
        return ""
    return raw.strip()


def run_hook(role: Optional[str] = None) -> None:
    """Entry point for the SubagentStop hook.

    The ``role`` argument is accepted for backward compatibility with any
    surviving configurations that still pass ``--role``; it is ignored.
    """
    del role  # gate removed — see module docstring
    try:
        from runtime.harness.hook_helpers import find_project_root, get_session_id, resolve_yoke_db

        project_root = find_project_root()
        db_path = resolve_yoke_db()
        if not db_path or not os.path.isfile(db_path):
            return

        agent_dir = os.environ.get("CLAUDE_PROJECT_DIR", "")
        session_id = get_session_id()
        if session_id in ("unknown", ""):
            session_id = _read_session_id_from_hook_stdin()
        if session_id in ("unknown", ""):
            session_id = f"{int(os.times().elapsed)}-{os.getpid()}"

        script_dir = os.environ.get("YOKE_SCRIPT_DIR") or os.path.join(
            project_root,
            ".agents",
            "skills",
            "yoke",
            "scripts",
        )
        ctx = process_dispatch_chains(
            db_path=db_path,
            script_dir=script_dir,
            project_root=project_root,
            agent_dir=agent_dir,
            session_id=session_id,
        )
        _emit_auto_commit_warning(ctx)
        emit_harness_session_stopped(script_dir, session_id, ctx)
    except Exception:
        return


def main() -> None:
    """CLI wrapper for the SubagentStop hook."""
    parser = argparse.ArgumentParser(prog="agent_stop")
    parser.add_argument(
        "command",
        nargs="?",
        default="hook",
        choices=["hook"],
    )
    # ``--role`` is accepted but ignored; retained so any config still passing
    # ``--role engineer`` / ``--role tester`` does not crash the hook.
    parser.add_argument(
        "--role",
        default=None,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    run_hook(role=args.role)


if __name__ == "__main__":
    main()


__all__ = [
    "BUSY_TIMEOUT_MS",
    "AutoCommitResult",
    "auto_commit_worktree",
    "StopContext",
    "process_dispatch_chains",
    "resolve_stop_reason",
    "build_stop_event_context",
    "determine_stop_outcome",
    "emit_harness_session_stopped",
    "_emit_auto_commit_warning",
    "run_hook",
    "main",
]
