"""Attribution and normalization helpers for observe telemetry.

Also exposes :class:`ToolEventRecord` — the universal tool-event schema
the shared policy pipeline dispatches on. ``tool_kind`` is one of
``bash`` / ``write`` / ``edit`` / ``apply_patch``; ``changed_paths`` is
the repo-relative paths the tool will mutate. The builder
(``build_tool_event_record``) and the ``tool_name -> tool_kind`` mapping
live in :mod:`harness_policy_pipeline` to keep this attribution module
under the file budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.events_crud import normalize_event_item_id
from yoke_core.domain.observe_db_reads import (
    connect_observe_read_db,
    repo_root_for_attribution,
)
from yoke_core.domain.observe_function_call_refs import extract_function_call_item_id


# ``tool_kind`` is the harness-neutral category the policy pipeline
# dispatches on. Concrete harness tool names (e.g. Claude's ``Edit`` /
# ``Write`` / ``Bash``, Codex's ``apply_patch``) map onto these values.
TOOL_KIND_BASH = "bash"
TOOL_KIND_WRITE = "write"
TOOL_KIND_EDIT = "edit"
TOOL_KIND_APPLY_PATCH = "apply_patch"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"

TOOL_KINDS: Tuple[str, ...] = (
    TOOL_KIND_BASH,
    TOOL_KIND_WRITE,
    TOOL_KIND_EDIT,
    TOOL_KIND_APPLY_PATCH,
)


@dataclass
class ToolEventRecord:
    """Harness-neutral tool-event payload consumed by the policy pipeline.

    ``tool_kind`` is the dispatch key. ``changed_paths`` is the list of
    repo-relative paths the tool will mutate. ``command`` carries the
    Bash command body; ``patch_body`` carries the raw Codex
    ``apply_patch`` envelope. Other fields mirror the PreToolUse hook
    payload so adapters can build a record without re-deriving context.
    """

    tool_kind: str = ""
    changed_paths: List[str] = field(default_factory=list)
    command: str = ""
    patch_body: str = ""
    tool_name: str = ""
    session_id: str = ""
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    cwd: str = ""
    project_dir: str = ""

def _normalize_dir(path: Optional[str]) -> Optional[str]:
    """Return a symlink-resolved directory path when it exists."""
    if not path:
        return None
    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    if resolved.is_dir():
        return str(resolved)
    return None


def _item_exists(conn: Any, item_id: str) -> bool:
    """Return True when the item exists in items."""
    lookup_id = normalize_event_item_id(item_id)
    if not lookup_id:
        return False
    row = conn.execute(
        f"SELECT id FROM items WHERE id = {_p(conn)} LIMIT 1",
        (lookup_id,),
    ).fetchone()
    return bool(row and row[0] is not None)


def _rollback_read_failure(conn: Any) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _resolve_dispatch_context(
    db_path: str, project_dir: str
) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    """Resolve item/task attribution from epic_dispatch_chains or worktree ownership."""
    normalized_project = _normalize_dir(project_dir)
    if not normalized_project:
        return None, None, None

    try:
        conn = connect_observe_read_db(db_path)
    except Exception:
        return None, None, None

    try:
        chain_row = conn.execute(
            """SELECT epic_id, current_task
               FROM epic_dispatch_chains
               WHERE worktree_path = {p}
                 AND current_task IS NOT NULL
                 AND current_task <> ''
               LIMIT 1""".format(p=_p(conn)),
            (normalized_project,),
        ).fetchone()
        if chain_row:
            return normalize_event_item_id(str(chain_row[0])), int(chain_row[1]), "dispatch"

        # deliberate case-sensitive match — worktree paths are POSIX-case-sensitive
        chain_row = conn.execute(
            """SELECT epic_id, current_task
               FROM epic_dispatch_chains
               WHERE {p} LIKE worktree_path || {p}
                 AND current_task IS NOT NULL
                 AND current_task <> ''
               LIMIT 1""".format(p=_p(conn)),
            (normalized_project, "/%"),
        ).fetchone()
        if chain_row:
            return normalize_event_item_id(str(chain_row[0])), int(chain_row[1]), "dispatch"

        worktree = Path(normalized_project).name
        fallback_rows = conn.execute(
            """SELECT id
               FROM items
               WHERE status NOT IN ('done', 'cancelled')
                 AND worktree = {p}
                 AND type <> 'epic'
               LIMIT 2""".format(p=_p(conn)),
            (worktree,),
        ).fetchall()
        if len(fallback_rows) == 1:
            return normalize_event_item_id(str(fallback_rows[0][0])), None, "worktree"
    except Exception:
        return None, None, None
    finally:
        conn.close()

    return None, None, None

def _resolve_main_session_attribution(
    db_path: str, project_dir: str, session_id: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """Resolve main-session attribution via DB session, in-flight item, or recent item.

    Resolution order:
      1. session_current  — current_item_id from harness_sessions (DB-backed)
      2. active_fallback  — single active non-epic item query
      3. session_recent   — recent_item_id from harness_sessions (DB-backed, 30-min window)
    """
    normalized_project = _normalize_dir(project_dir)
    repo_root = repo_root_for_attribution(db_path, project_dir)
    if not normalized_project or not repo_root:
        return None, None

    normalized_root = _normalize_dir(repo_root)
    if not normalized_root or normalized_project != normalized_root:
        return None, None

    try:
        conn = connect_observe_read_db(db_path)
    except Exception:
        return None, None

    try:
        # DB-backed current item from harness_sessions
        if session_id:
            try:
                row = conn.execute(
                    "SELECT current_item_id, recent_item_id, recent_item_recorded_at"
                    f" FROM harness_sessions WHERE session_id={_p(conn)}",
                    (session_id,),
                ).fetchone()
            except Exception:
                _rollback_read_failure(conn)
                row = None

            if row:
                current_item_id = row[0]
                if current_item_id and _item_exists(conn, str(current_item_id)):
                    return normalize_event_item_id(str(current_item_id)), "session_current"

        # Single active non-epic item
        active_rows = conn.execute(
            """SELECT id FROM items
               WHERE status IN (
                 'implementing',
                 'reviewing-implementation',
                 'reviewed-implementation',
                 'polishing-implementation',
                 'implemented',
                 'release'
               )
                 AND type <> 'epic'
               LIMIT 2"""
        ).fetchall()
        if len(active_rows) == 1:
            return normalize_event_item_id(str(active_rows[0][0])), "active_fallback"

        # DB-backed recent item from harness_sessions (30-min window)
        if session_id:
            try:
                if not row:
                    row = conn.execute(
                        "SELECT current_item_id, recent_item_id, recent_item_recorded_at"
                        f" FROM harness_sessions WHERE session_id={_p(conn)}",
                        (session_id,),
                    ).fetchone()
            except Exception:
                _rollback_read_failure(conn)
                row = None

            if row:
                recent_item_id = row[1]
                recent_recorded_at = row[2]
                if recent_item_id and recent_recorded_at:
                    try:
                        ts_str = str(recent_recorded_at).replace("Z", "+00:00")
                        parsed = datetime.fromisoformat(ts_str)
                        # Older rows may carry naive UTC timestamps.
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        age = int(datetime.now(timezone.utc).timestamp()) - int(
                            parsed.timestamp()
                        )
                    except (TypeError, ValueError):
                        age = -1
                    if 0 <= age <= 1800 and _item_exists(conn, str(recent_item_id)):
                        return normalize_event_item_id(str(recent_item_id)), "session_recent"

    except Exception:
        return None, None
    finally:
        conn.close()

    return None, None

def _compute_duration(db_path: str, tool_use_id: str) -> Optional[int]:
    """Compute duration_ms from a HarnessToolCallStarted event matched by tool_use_id."""
    try:
        conn = connect_observe_read_db(db_path)
        row = conn.execute(
            """SELECT created_at FROM events
               WHERE event_name = 'HarnessToolCallStarted'
                 AND tool_use_id = {p}
               ORDER BY created_at DESC LIMIT 1""".format(p=_p(conn)),
            (tool_use_id,),
        ).fetchone()
        conn.close()
        if row and row[0]:
            start_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            end_dt = datetime.now(timezone.utc)
            delta = int((end_dt - start_dt).total_seconds() * 1000)
            if 0 <= delta <= 600000:  # sanity: 0..10min
                return delta
    except Exception:
        pass
    return None


def _resolve_explicit_refs(rec: EventRecord, db_path: Optional[str]) -> None:
    """Override stale marker/active/done fallbacks when the tool call contains
    an unambiguous item reference."""
    explicit_item = None
    explicit_source = None

    if rec.tool_name == "Bash" and rec.command:
        cmd = rec.command
        # Display-form YOK-N patterns
        sun_refs = set(re.findall(r"YOK-(\d+)", cmd))
        # Numeric refs in item get/update commands
        cmd_refs = set(re.findall(r"(?:items\s+(?:get|update)\s+)(\d+)", cmd))
        # Epic refs in legacy wrapper commands
        epic_cmd_refs = set(
            re.findall(r"(?:yoke-db\.sh\s+epic\s+\S+)\s+(\d+)", cmd)
        )
        # Numeric refs in other yoke scripts
        script_refs = set(
            re.findall(
                r"(?:create-worktree\.sh|done-transition\.sh|deploy-pipeline\.sh"
                r"|classify-browser-qa\.sh|qa-gate-check\.sh)\s+(\d+)",
                cmd,
            )
        )
        # Flag-based item refs
        flag_refs = set(re.findall(r"--item(?:-id)?\s+(\d+)", cmd))
        # Function-call envelope refs (curl POST to /v1/functions/call)
        fn_call_id = extract_function_call_item_id(cmd)
        fn_call_refs: set = {fn_call_id} if fn_call_id else set()
        all_refs = sun_refs | cmd_refs | epic_cmd_refs | script_refs | flag_refs | fn_call_refs
        if len(all_refs) == 1:
            explicit_item = all_refs.pop()
            explicit_source = (
                "explicit_function_call_envelope"
                if explicit_item in fn_call_refs
                else "explicit_bash_ref"
            )
        elif len(all_refs) == 0 and db_path:
            # Run-based attribution
            run_refs = re.findall(r"(run-\d{8}-\d{3})", cmd)
            if run_refs:
                unique_runs = list(set(run_refs))
                if len(unique_runs) == 1:
                    try:
                        conn = connect_observe_read_db(db_path)
                        rows = conn.execute(
                            "SELECT DISTINCT item_id FROM deployment_run_items "
                            f"WHERE run_id = {_p(conn)}",
                            (unique_runs[0],),
                        ).fetchall()
                        conn.close()
                        if len(rows) == 1:
                            explicit_item = str(rows[0][0])
                            explicit_source = "explicit_bash_ref"
                    except Exception:
                        pass
    elif rec.tool_name in ("Read", "Write", "Edit") and rec.file_path:
        wt_match = re.search(r"\.worktrees/YOK-(\d+)/", rec.file_path)
        if wt_match:
            explicit_item = wt_match.group(1)
            explicit_source = "explicit_path_ref"

    if explicit_item:
        rec.item_id = explicit_item
        rec.attribution_source = explicit_source
