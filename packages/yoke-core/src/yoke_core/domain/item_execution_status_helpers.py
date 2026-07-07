"""Per-section collectors for :mod:`item_execution_status`.

Read-only helpers that keep projection assembly, rendering, and CLI code
small enough for Yoke's authored-file line cap.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.file_budget_paths import extract_file_budget_paths
from yoke_core.domain.file_line_check import LIMIT as LINE_LIMIT
from yoke_core.domain.file_line_check_helpers import line_count_file
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gate_summary import render_gate_summary
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_reclaim_activity import latest_activity

NEAR_CAP_THRESHOLD = 300  # AGENTS.md design target.
PROGRESS_LOG_STALE_SECONDS = 24 * 60 * 60
PROGRESS_LOG_SECTION = "Progress Log"
DEFAULT_QA_TARGET = "reviewed-implementation"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def age_seconds(ts: Optional[str], *, now: datetime) -> Optional[int]:
    parsed = parse_iso(ts)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def normalize_item_id(raw: str) -> int:
    text = str(raw).strip()
    if text.upper().startswith("YOK-"):
        text = text.split("-", 1)[1]
    return int(text)


def worktree_state(
    item_id: int,
    branch: Optional[str],
    *,
    db_path: Optional[str],
    repo_root: Path,
    warnings: List[str],
) -> Dict[str, Any]:
    try:
        from yoke_core.domain.worktree_item_resolve import (
            resolve_item_worktree,
        )

        resolved = resolve_item_worktree(f"YOK-{item_id}", db_path=db_path)
        paths = list(resolved.paths)
        branches = list(resolved.branches)
        has_recorded_or_live = bool(branch or (resolved.exists and paths))
        if not has_recorded_or_live:
            return {
                "state": "none", "branch": None, "path": None,
                "exists": False, "scope": resolved.scope,
                "branches": [], "paths": [], "repo": resolved.repo,
            }
        if paths and not resolved.exists:
            warnings.append(
                "items.worktree set but one or more directories are missing: "
                + ", ".join(paths)
            )
        return {
            "state": "set",
            "branch": resolved.branch or (branches[0] if branches else branch),
            "path": resolved.path or (paths[0] if len(paths) == 1 else None),
            "exists": resolved.exists,
            "scope": resolved.scope,
            "branches": branches,
            "paths": paths,
            "repo": resolved.repo,
        }
    except Exception:
        if not branch:
            return {
                "state": "none", "branch": None, "path": None,
                "exists": False, "scope": "item", "branches": [],
                "paths": [], "repo": str(repo_root),
            }
        wt_path = repo_root / ".worktrees" / branch
        exists = wt_path.is_dir()
        if not exists:
            warnings.append(
                f"items.worktree set but directory missing: {wt_path}"
            )
        return {
            "state": "set",
            "branch": str(branch),
            "path": str(wt_path),
            "exists": exists,
            "scope": "item",
            "branches": [str(branch)],
            "paths": [str(wt_path)],
            "repo": str(repo_root),
        }


def file_budget_root(wt_state: Dict[str, Any], repo_root: Path) -> Path:
    path = wt_state.get("path")
    if wt_state.get("exists") and path:
        return Path(str(path))
    for raw in wt_state.get("paths", []):
        if raw and Path(str(raw)).is_dir():
            return Path(str(raw))
    return repo_root


def health_state(
    *,
    warnings: List[str],
    path_claims: Dict[str, Any],
    qa_summary: Dict[str, Any],
) -> Dict[str, Any]:
    if path_claims.get("latest_blocker_reason"):
        state = "blocked"
    elif int(qa_summary.get("unsatisfied_blocking") or 0) > 0:
        state = "blocked"
    elif warnings:
        state = "warning"
    else:
        state = "ok"
    return {"state": state, "warning_count": len(warnings)}


def collect_work_claim(
    conn: Any, item_id: int, *, now: datetime
) -> Dict[str, Any]:
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT id, session_id, claim_type, claimed_at "
        f"FROM work_claims WHERE target_kind='item' AND item_id={p} "
        "AND released_at IS NULL ORDER BY id DESC LIMIT 1",
        (item_id,),
    )
    if row is None:
        return {"state": "none"}
    activity_at = latest_activity(conn, str(row["session_id"]))
    return {
        "state": "active",
        "claim_id": int(row["id"]),
        "holder_session_id": str(row["session_id"]),
        "claim_type": str(row["claim_type"]),
        "claimed_at": str(row["claimed_at"]),
        "claim_age_seconds": age_seconds(row["claimed_at"], now=now),
        "last_heartbeat": str(activity_at) if activity_at else "",
        "heartbeat_age_seconds": age_seconds(activity_at, now=now),
    }


def collect_path_claims(
    conn: Any, item_id: int
) -> Dict[str, Any]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT id, state, blocked_reason FROM path_claims "
        f"WHERE item_id={p} ORDER BY id",
        (item_id,),
    )
    state_counts: Dict[str, int] = {}
    latest_blocker: Optional[str] = None
    latest_blocker_id: Optional[int] = None
    for r in rows:
        state = str(r["state"])
        state_counts[state] = state_counts.get(state, 0) + 1
        reason = str(r["blocked_reason"]) if r["blocked_reason"] else None
        cid = int(r["id"])
        if state == "blocked" and reason and (
            latest_blocker_id is None or cid > latest_blocker_id
        ):
            latest_blocker, latest_blocker_id = reason, cid
    return {
        "total": len(rows),
        "state_counts": state_counts,
        "latest_blocker_reason": latest_blocker,
        "latest_blocker_claim_id": latest_blocker_id,
    }


def latest_progress_entry(
    content: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Extract the most recent ``## <ts> entry — <headline>`` pair.

    The canonical Progress Log convention (AGENTS.md) uses an em-dash
    between timestamp and headline. Entries without the em-dash still
    expose their timestamp; the headline is ``None``.
    """
    last_ts: Optional[str] = None
    last_headline: Optional[str] = None
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("## ") or " entry" not in stripped:
            continue
        body = stripped[3:].strip()
        last_ts = body.split(" entry", 1)[0].strip() or None
        if "—" in body:
            last_headline = body.split("—", 1)[1].strip() or None
        else:
            last_headline = None
    return last_headline, last_ts


def collect_progress_log(
    conn: Any, item_id: int, *, now: datetime
) -> Dict[str, Any]:
    p = _p(conn)
    row = query_one(
        conn,
        "SELECT content, updated_at FROM item_sections "
        f"WHERE item_id={p} AND section_name={p}",
        (item_id, PROGRESS_LOG_SECTION),
    )
    if row is None or not (row["content"] or "").strip():
        return {"state": "missing"}
    headline, entry_at = latest_progress_entry(row["content"])
    entry_age = age_seconds(entry_at, now=now)
    return {
        "state": "present",
        "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
        "latest_headline": headline,
        "latest_entry_at": entry_at,
        "latest_entry_age_seconds": entry_age,
        "is_stale": bool(
            entry_age is not None and entry_age > PROGRESS_LOG_STALE_SECONDS
        ),
    }


def collect_file_budget(
    spec_text: str, *, repo_root: Path
) -> Dict[str, Any]:
    paths = extract_file_budget_paths(spec_text or "")
    entries: List[Dict[str, Any]] = []
    near_cap = over_cap = missing = 0
    for rel in paths:
        abs_path = repo_root / rel
        exists = abs_path.is_file()
        line_count = line_count_file(abs_path) if exists else 0
        is_near = bool(exists and line_count > NEAR_CAP_THRESHOLD)
        is_over = bool(exists and line_count > LINE_LIMIT)
        missing += 0 if exists else 1
        near_cap += int(is_near)
        over_cap += int(is_over)
        entries.append({
            "path": rel,
            "exists": exists,
            "line_count": line_count if exists else None,
            "near_cap": is_near,
            "over_cap": is_over,
        })
    return {
        "total": len(entries),
        "near_cap_count": near_cap,
        "over_cap_count": over_cap,
        "missing_count": missing,
        "near_cap_threshold": NEAR_CAP_THRESHOLD,
        "limit": LINE_LIMIT,
        "paths": entries,
    }


def collect_qa(
    conn: Any, db_path: str, item_id: int
) -> Dict[str, Any]:
    if not _table_exists(conn, "qa_requirements"):
        return {"state": "no_qa_tables"}
    summary = render_gate_summary(
        GateTarget(item_id=item_id), db_path,
        transition_name=DEFAULT_QA_TARGET,
    )
    requirements = summary.get("requirements") or []
    blocking_total = sum(
        1 for r in requirements
        if r.get("blocking_mode") == "blocking" and not r.get("waived_at")
    )
    state = "configured" if requirements else "no_requirements"
    return {
        "state": state,
        "target": summary.get("target"),
        "transition": summary.get("transition"),
        "satisfied": summary.get("satisfied"),
        "blocking_total": blocking_total,
        "unsatisfied_blocking": summary.get(
            "blocking_unsatisfied_count", 0
        ),
        "browser_unsatisfied": summary.get("browser_unsatisfied_count", 0),
        "e2e_unsatisfied": summary.get("e2e_unsatisfied_count", 0),
    }


def collect_latest_transition(
    conn: Any, item_id: int, *, now: datetime
) -> Dict[str, Any]:
    """Latest status-transition row for the item (state, not telemetry)."""
    from yoke_core.domain.item_status_transitions import latest_transition

    row = latest_transition(conn, item_id)
    if row is None:
        return {"state": "none"}
    return {
        "state": "present",
        "task_num": row["task_num"],
        "from_status": row["from_status"],
        "to_status": str(row["to_status"]),
        "source": row["source"],
        "latest_at": str(row["created_at"]),
        "latest_age_seconds": age_seconds(row["created_at"], now=now),
    }
