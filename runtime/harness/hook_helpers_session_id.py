"""Project-root, session ID, dispatch-context, and hook-JSON helpers.

The lower-level lookups invoked by every Yoke hook owner: locate the
main worktree, resolve explicit test DB overrides, resolve the session ID
across harnesses, parse hook JSON via dot-paths, and walk the
``epic_dispatch_chains`` table to find the active dispatch chain for a
worktree.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Optional, Tuple

from yoke_core.domain.db_helpers import BUSY_TIMEOUT_MS


# ---------------------------------------------------------------------------
# Project root resolution
# ---------------------------------------------------------------------------


def find_project_root(claude_project_dir: Optional[str] = None) -> str:
    """Resolve the main repository root.

    In worktree contexts, CLAUDE_PROJECT_DIR points to the worktree, not the
    main repo. This function always prefers the main worktree root (first
    entry from ``git worktree list --porcelain``) because the DB and shared
    state live there.

    Falls back to *claude_project_dir* if git is unavailable.
    """
    candidate = claude_project_dir or os.environ.get("CLAUDE_PROJECT_DIR", "")

    # Preferred: git worktree list always shows main worktree first.
    try:
        git_args = ["git"]
        if candidate:
            git_args.extend(["-C", candidate])
        git_args.extend(["worktree", "list", "--porcelain"])
        result = subprocess.run(
            git_args,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("worktree "):
                    main_root = line[len("worktree "):]
                    try:
                        from yoke_core.domain import yoke_connected_env

                        binding = yoke_connected_env.find_binding(Path(main_root))
                    except Exception:
                        binding = None
                    if binding:
                        return main_root
                    break
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass

    # Fallback: candidate itself might carry the connected-env binding.
    if candidate:
        try:
            from yoke_core.domain import yoke_connected_env

            binding = yoke_connected_env.find_binding(Path(candidate))
        except Exception:
            binding = None
        if binding:
            return candidate

    # Last resort
    return candidate or "."


def resolve_yoke_db(script_dir: Optional[str] = None) -> str:
    """Return an explicit test DB override, or ``""`` for Postgres authority."""
    root = find_project_root()
    connected_env = None
    try:
        from yoke_core.domain import yoke_connected_env

        connected_env = yoke_connected_env.load_active(Path(root or "."))
    except Exception:
        connected_env = None

    current = os.environ.get("YOKE_DB", "")
    if current:
        try:
            from yoke_core.domain.yoke_connected_env_retired_db import (
                retired_yoke_db_reason,
            )

            if retired_yoke_db_reason(connected_env):
                return ""
        except Exception:
            pass
        return current

    return ""


# ---------------------------------------------------------------------------
# Session ID resolution
# ---------------------------------------------------------------------------


def get_session_id(workspace: Optional[str] = None) -> str:
    """Resolve the current session ID from the canonical ambient chain.

    Resolution order (owned by
    :mod:`yoke_core.domain.session_ambient_identity`):
      1. $YOKE_SESSION_ID → $CLAUDE_SESSION_ID → $CODEX_THREAD_ID
      2. hook-written process-anchor registry (ancestry walk)
      3. "unknown" fallback

    Yoke hosts N parallel sessions per (executor, workspace) — multiple
    Claude Desktop windows on the same checkout, sub-agent dispatches into
    worktrees that share the workspace string, reactivated sessions whose
    predecessor has not yet emitted HarnessSessionEnded. There is no "the
    current session" derivable from (executor, workspace); the ambient
    chain self-identifies per process (distinct harness ancestor pids), and
    hook callers may also read the payload's structured ``session_id``.
    """
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or "unknown"


# ---------------------------------------------------------------------------
# Dispatch context resolution
# ---------------------------------------------------------------------------


def resolve_dispatch_context(
    db_path: str,
    agent_dir: str,
) -> Optional[Tuple[str, str, str]]:
    """Look up the active dispatch chain for this worktree.

    Returns ``(epic_id, task_num, item_id)`` or ``None`` if no match.

    Queries epic_dispatch_chains for a chain whose worktree_path matches the
    given agent directory.  Falls back to prefix match and non-epic item
    worktree match.
    """
    if not agent_dir:
        return None

    try:
        from yoke_core.domain.db_helpers import connect as _connect

        conn = _connect(db_path)

        # Exact match on worktree_path
        row = conn.execute(
            """SELECT epic_id, COALESCE(current_task, ''), epic_id
               FROM epic_dispatch_chains
               WHERE worktree_path = %s
                 AND current_task IS NOT NULL
                 AND current_task <> ''
               LIMIT 1""",
            (agent_dir,),
        ).fetchone()
        if row:
            conn.close()
            return (str(row[0]), str(row[1]), str(row[2]))

        # prefix match for nested subdirs
        row = conn.execute(
            """SELECT epic_id, COALESCE(current_task, ''), epic_id
               FROM epic_dispatch_chains
               WHERE %s LIKE worktree_path || %s
                 AND current_task IS NOT NULL
                 AND current_task <> ''
               LIMIT 1""",
            (agent_dir, "/%"),
        ).fetchone()
        if row:
            conn.close()
            return (str(row[0]), str(row[1]), str(row[2]))

        # Fallback: non-epic items by worktree basename
        wt_basename = os.path.basename(agent_dir)
        rows = conn.execute(
            """SELECT id FROM items
               WHERE status NOT IN ('done', 'cancelled')
                 AND worktree = %s
                 AND type <> 'epic'
               LIMIT 2""",
            (wt_basename,),
        ).fetchall()
        conn.close()

        if len(rows) == 1:
            return ("", "", str(rows[0][0]))

        return None
    except (Exception,):
        return None


# ---------------------------------------------------------------------------
# Hook JSON parsing
# ---------------------------------------------------------------------------


def parse_hook_json(json_str: str, dot_path: str) -> str:
    """Extract a dot-path field from hook JSON.

    Args:
        json_str: Raw JSON string (the buffered hook input).
        dot_path: Dot-separated path (e.g., ``tool_name``, ``tool_input.command``).

    Returns:
        Extracted value as string, or empty string on error.
    """
    try:
        data = json.loads(json_str)
        keys = dot_path.split(".")
        val: Any = data
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key, "")
            else:
                return ""
        if val is None:
            return ""
        return str(val)[:4096]
    except (json.JSONDecodeError, TypeError):
        return ""
