"""Attribution and normalization helpers for observe telemetry."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.events_crud import normalize_event_item_id
from yoke_core.domain.observe_db_reads import (
    connect_observe_read_db,
    repo_root_for_attribution,
)
from yoke_core.domain.observe_function_call_refs import extract_function_call_item_id
from yoke_core.domain.observe_tool_event import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_BASH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    TOOL_KINDS,
    ToolEventRecord,
)
from yoke_core.domain.workflow_behavior import generates_task_graph
from yoke_core.domain.workflow_runtime import ENGINE_TERMINAL_STAGE_IDS, workflow_runtime_from_row

if TYPE_CHECKING:
    # Imported only for annotations: observe_parsing imports this module at
    # runtime, so a live import here would be circular.
    from yoke_core.domain.observe_parsing import EventRecord


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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
            """SELECT c.epic_id, c.current_task
               FROM epic_dispatch_chains c
               JOIN item_worktrees iw ON iw.id = c.item_worktree_id
               WHERE iw.path = {p}
                 AND iw.state = 'active'
                 AND c.current_task IS NOT NULL
                 AND c.current_task <> ''
               LIMIT 1""".format(p=_p(conn)),
            (normalized_project,),
        ).fetchone()
        if chain_row:
            return (
                normalize_event_item_id(str(chain_row[0])),
                int(chain_row[1]),
                "dispatch",
            )

        chain_row = conn.execute(
            """SELECT c.epic_id, c.current_task
               FROM epic_dispatch_chains c
               JOIN item_worktrees iw ON iw.id = c.item_worktree_id
               WHERE {p} LIKE iw.path || {p}
                 AND iw.state = 'active'
                 AND c.current_task IS NOT NULL
                 AND c.current_task <> ''
               LIMIT 1""".format(p=_p(conn)),
            (normalized_project, "/%"),
        ).fetchone()
        if chain_row:
            return (
                normalize_event_item_id(str(chain_row[0])),
                int(chain_row[1]),
                "dispatch",
            )

        worktree = Path(normalized_project).name
        fallback_rows = conn.execute(
            """SELECT DISTINCT i.id, i.status, i.workflow_id, i.workflow_version_id,
                      v.version, v.definition_json, v.definition_digest
               FROM items i
               JOIN item_worktrees iw ON iw.item_id = i.id
               JOIN workflow_versions v ON v.id = i.workflow_version_id
               WHERE iw.state = 'active'
                 AND (iw.branch = {p} OR iw.path = {p})
               """.format(p=_p(conn)),
            (worktree, normalized_project),
        ).fetchall()
        fallback_rows = [
            row for row in fallback_rows if str(row["status"]) not in
            workflow_runtime_from_row(row).terminal_stage_ids | ENGINE_TERMINAL_STAGE_IDS
        ]
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
      2. active_fallback  — single active item without generated child tasks
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
                    return normalize_event_item_id(
                        str(current_item_id)
                    ), "session_current"

        active_rows = conn.execute(
            """SELECT i.id, i.status, i.workflow_id, i.workflow_version_id,
                      v.version, v.definition_json, v.definition_digest
               FROM items i
               JOIN workflow_versions v ON v.id = i.workflow_version_id
               WHERE i.status IN (
                 'implementing',
                 'reviewing-implementation',
                 'reviewed-implementation',
                 'polishing-implementation',
                 'implemented',
                 'release'
               )
               """
        ).fetchall()
        active_rows = [
            row for row in active_rows
            if not generates_task_graph(workflow_runtime_from_row(row))
        ]
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
                        return normalize_event_item_id(
                            str(recent_item_id)
                        ), "session_recent"

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
        epic_cmd_refs = set(re.findall(r"(?:yoke-db\.sh\s+epic\s+\S+)\s+(\d+)", cmd))
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
        all_refs = (
            sun_refs | cmd_refs | epic_cmd_refs | script_refs | flag_refs | fn_call_refs
        )
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


__all__ = [
    "TOOL_KIND_APPLY_PATCH",
    "TOOL_KIND_BASH",
    "TOOL_KIND_EDIT",
    "TOOL_KIND_WRITE",
    "TOOL_KINDS",
    "ToolEventRecord",
]
