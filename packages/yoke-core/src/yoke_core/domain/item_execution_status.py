"""Compact item execution-status read model.

V0 projection that stitches existing item, claim, path-claim, QA,
Progress Log, File Budget, and event facts into one diagnostic shape.
Read-only: never mutates rows, never parses chat-transcript text, never
schedules work. Future absorption target: a living execution-plan /
journal projection.

Per-section collectors live in the sibling
:mod:`yoke_core.domain.item_execution_status_helpers` module so this
module stays focused on orchestration, rendering, and the CLI surface.

CLI::

    python3 -m yoke_core.domain.item_execution_status YOK-N [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_one
from yoke_core.domain.item_execution_status_helpers import (
    LINE_LIMIT,
    NEAR_CAP_THRESHOLD,
    collect_latest_transition,
    collect_file_budget,
    collect_path_claims,
    collect_progress_log,
    collect_qa,
    collect_work_claim,
    file_budget_root,
    health_state,
    normalize_item_id,
    worktree_state,
)


def _row_value(row: Any, key: str, index: int) -> Any:
    try:
        return row[key]
    except (KeyError, TypeError, IndexError):
        return row[index]


def _item_dict(item: Any) -> Dict[str, Any]:
    item_id = _row_value(item, "id", 0)
    worktree = _row_value(item, "worktree", 5)
    return {
        "id": int(item_id),
        "yok_id": f"YOK-{int(item_id)}",
        "title": str(_row_value(item, "title", 1)),
        "type": str(_row_value(item, "type", 2)),
        "status": str(_row_value(item, "status", 3)),
        "project": str(_row_value(item, "project", 4)),
        "worktree": str(worktree) if worktree else None,
    }


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _collect_warnings(
    *,
    path_claims: Dict[str, Any],
    progress_log: Dict[str, Any],
    file_budget: Dict[str, Any],
) -> List[str]:
    out: List[str] = []
    if path_claims.get("latest_blocker_reason"):
        out.append(
            f"path_claim blocked: {path_claims['latest_blocker_reason']}"
        )
    if progress_log["state"] == "missing":
        out.append("Progress Log section missing")
    elif progress_log.get("is_stale"):
        out.append("Progress Log latest entry is stale")
    if file_budget["over_cap_count"]:
        out.append(
            f"{file_budget['over_cap_count']} File Budget path(s) over "
            f"the {LINE_LIMIT}-line cap"
        )
    elif file_budget["near_cap_count"]:
        out.append(
            f"{file_budget['near_cap_count']} File Budget path(s) near "
            f"the {NEAR_CAP_THRESHOLD}-line design target"
        )
    return out


def build_projection(
    item_id: int,
    *,
    conn: Optional[Any] = None,
    db_path: Optional[str] = None,
    repo_root: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Return the compact execution-status projection for ``item_id``."""
    own_conn = conn is None
    if conn is None:
        conn = connect(db_path)
    now = now or datetime.now(timezone.utc)
    repo_root = repo_root or Path.cwd()
    try:
        item = query_one(
            conn,
            "SELECT i.id, i.title, i.type, i.status, p.slug AS project, "
            "i.worktree, i.spec "
            "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
            f"WHERE i.id={_p(conn)}",
            (item_id,),
        )
        if item is None:
            return {
                "ok": False,
                "error": f"item not found: YOK-{item_id}",
                "item_id": item_id,
            }
        item_dict = _item_dict(item)
        warnings: List[str] = []
        wt_state = worktree_state(
            item_id,
            _row_value(item, "worktree", 5),
            db_path=db_path,
            repo_root=repo_root,
            warnings=warnings,
        )
        path_claims = collect_path_claims(conn, item_id)
        progress_log = collect_progress_log(conn, item_id, now=now)
        file_budget = collect_file_budget(
            _row_value(item, "spec", 6) or "",
            repo_root=file_budget_root(wt_state, repo_root),
        )
        warnings.extend(_collect_warnings(
            path_claims=path_claims,
            progress_log=progress_log,
            file_budget=file_budget,
        ))
        if db_path:
            try:
                qa_summary = collect_qa(conn, db_path, item_id)
            except Exception as exc:  # pragma: no cover - defensive
                qa_summary = {"state": "error", "error": str(exc)}
                warnings.append(f"qa summary failed: {exc}")
        else:
            qa_summary = {"state": "db_path_unresolved"}
        health = health_state(
            warnings=warnings, path_claims=path_claims,
            qa_summary=qa_summary,
        )
        return {
            "ok": True,
            "item": item_dict,
            "lifecycle": {
                "current": item_dict["status"], "type": item_dict["type"],
            },
            "work_claim": collect_work_claim(conn, item_id, now=now),
            "worktree": wt_state,
            "path_claims": path_claims,
            "progress_log": progress_log,
            "file_budget": file_budget,
            "qa": qa_summary,
            "latest_transition": collect_latest_transition(
                conn, item_id, now=now,
            ),
            "health": health,
            "warnings": warnings,
        }
    finally:
        if own_conn:
            conn.close()


def _render_path_claims(pc: Dict[str, Any], lines: List[str]) -> None:
    if pc["total"]:
        states = ", ".join(
            f"{k}={v}" for k, v in sorted(pc["state_counts"].items())
        )
        lines.append(f"  path claims: total={pc['total']}  {states}")
        if pc["latest_blocker_reason"]:
            lines.append(f"    blocker: {pc['latest_blocker_reason']}")
    else:
        lines.append("  path claims: none")


def render_text(projection: Dict[str, Any]) -> str:
    """Compact human-readable rendering of the projection dict."""
    if not projection.get("ok"):
        return f"ERROR: {projection.get('error', 'unknown error')}"
    item = projection["item"]
    work, wt = projection["work_claim"], projection["worktree"]
    pc, pl = projection["path_claims"], projection["progress_log"]
    fb, qa, ev = (
        projection["file_budget"],
        projection["qa"],
        projection["latest_transition"],
    )
    lines = [
        f"{item['yok_id']} [{item['type']}] — {item['title']}",
        f"  status: {item['status']}    project: {item['project']}",
        f"  health: {projection['health']['state']}",
    ]
    if work["state"] == "active":
        lines.append(
            f"  work claim: held by {work['holder_session_id']} "
            f"(claim {work['claim_id']}, hb_age="
            f"{work.get('heartbeat_age_seconds')}s)"
        )
    else:
        lines.append("  work claim: none")
    lines.append(
        "  worktree: "
        + (
            f"{wt['branch']} ({'exists' if wt['exists'] else 'MISSING'})"
            if wt["state"] == "set" else "none"
        )
    )
    _render_path_claims(pc, lines)
    if pl["state"] == "present":
        headline = pl.get("latest_headline") or "(no headline)"
        ts = pl.get("latest_entry_at") or "no ts"
        lines.append(f"  progress log: {headline} ({ts})")
    else:
        lines.append("  progress log: missing")
    lines.append(
        f"  file budget: {fb['total']} path(s)  "
        f"near_cap={fb['near_cap_count']}  over_cap={fb['over_cap_count']}  "
        f"missing={fb['missing_count']}"
    )
    if qa.get("state") in {"configured", "no_requirements"}:
        lines.append(
            f"  qa ({qa.get('transition')}): "
            f"satisfied={qa.get('satisfied')} "
            f"blocking={qa.get('blocking_total', 0)} "
            f"unsatisfied={qa.get('unsatisfied_blocking', 0)}"
        )
    else:
        lines.append(f"  qa: {qa.get('state', 'unknown')}")
    if ev.get("state") == "present":
        task_part = (
            f" (task {ev['task_num']})" if ev.get("task_num") is not None else ""
        )
        lines.append(
            f"  latest transition: {ev.get('from_status') or '?'} -> "
            f"{ev['to_status']}{task_part} @ {ev['latest_at']}"
        )
    if projection["warnings"]:
        lines.append("  warnings:")
        for w in projection["warnings"]:
            lines.append(f"    - {w}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.item_execution_status",
        description=(
            "Compact item execution-status read model. Read-only "
            "projection of items/claims/QA/Progress Log/File Budget facts."
        ),
    )
    parser.add_argument("item_id", help="Item id (bare integer or YOK-N)")
    parser.add_argument("--json", action="store_true", help="Emit JSON.")
    parser.add_argument(
        "--repo-root", default=None,
        help="Repo root for File Budget line counts (default: cwd)",
    )
    args = parser.parse_args(argv)
    try:
        item_id = normalize_item_id(args.item_id)
    except (TypeError, ValueError):
        print(
            f"ERROR: cannot parse item id '{args.item_id}'", file=sys.stderr
        )
        return 2
    repo_root = (
        Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
    )
    projection = build_projection(item_id, repo_root=repo_root)
    if args.json:
        print(json.dumps(projection, indent=2, sort_keys=True))
    else:
        print(render_text(projection))
    return 0 if projection.get("ok") else 1


__all__ = [
    "build_projection",
    "render_text",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
