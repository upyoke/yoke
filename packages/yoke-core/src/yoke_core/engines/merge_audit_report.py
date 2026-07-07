"""Markdown report generation for merge readiness audits."""

from __future__ import annotations

import os
import re
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect, query_rows, query_one, query_scalar
from yoke_core.domain.lifecycle import sql_terminal_success_list


# One row per distinct worktree branch for an epic, ordered by the earliest
# task in each worktree. GROUP BY worktree already collapses duplicates, so no
# DISTINCT is needed — and omitting it keeps the ORDER BY MIN(task_num)
# aggregate portable (Postgres rejects ORDER BY expressions absent from the
# SELECT list under SELECT DISTINCT).
def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _epic_worktrees_sql(conn) -> str:
    p = _p(conn)
    return (
        "SELECT worktree FROM epic_tasks "
        f"WHERE epic_id = {p} AND worktree IS NOT NULL "
        "GROUP BY worktree ORDER BY MIN(task_num)"
    )


def _parent():
    from yoke_core.engines import merge_audit as _ma
    return _ma

def generate_report(epic_filter: Optional[int] = None) -> str:
    """Generate the full merge readiness audit report.

    Parameters
    ----------
    epic_filter:
        If provided, scope the audit to a single epic ID.

    Returns
    -------
    str
        Markdown report.
    """
    ma = _parent()
    _resolve_repo_root = ma._resolve_repo_root
    _branch_exists = ma._branch_exists
    _commits_ahead = ma._commits_ahead
    _worktree_path_for_branch = ma._worktree_path_for_branch
    _worktree_dirty_files = ma._worktree_dirty_files
    _has_merge_tree = ma._has_merge_tree
    _list_sun_branches = ma._list_sun_branches
    _check_conflict = ma._check_conflict
    _now_iso = ma._now_iso

    conn = connect()
    repo_root = _resolve_repo_root()

    lines: List[str] = []
    lines.append("# Merge Readiness Audit")
    lines.append(f"Generated: {_now_iso()}")
    lines.append("")

    # Terminal success statuses for SQL
    terminal_success_sql = sql_terminal_success_list()


    if epic_filter is not None:
        epic_ids_rows = query_rows(
            conn,
            f"SELECT DISTINCT epic_id FROM epic_tasks WHERE epic_id = {_p(conn)} "
            "AND worktree IS NOT NULL",
            (epic_filter,),
        )
    else:
        epic_ids_rows = query_rows(
            conn,
            "SELECT DISTINCT epic_id FROM epic_tasks WHERE worktree IS NOT NULL ORDER BY epic_id",
        )

    epic_ids = [row["epic_id"] for row in epic_ids_rows]

    has_epic_content = False
    warning_count = 0

    for eid in epic_ids:
        # Get item info
        item_row = query_one(
            conn,
            f"SELECT id, title, status FROM items WHERE id = {_p(conn)} LIMIT 1",
            (eid,),
        )
        if item_row is None:
            continue

        item_id = item_row["id"]
        item_title = item_row["title"]
        item_status = item_row["status"]

        # Get distinct worktree branches for this epic.
        wt_rows = query_rows(conn, _epic_worktrees_sql(conn), (eid,))
        worktrees = [r["worktree"] for r in wt_rows]

        # Check if any branches still exist (unmerged)
        has_branches = any(_branch_exists(repo_root, wt) for wt in worktrees)
        if not has_branches:
            continue

        has_epic_content = True

        # Task completion stats
        total_tasks = query_scalar(
            conn, f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id = {_p(conn)}", (eid,)
        ) or 0
        done_tasks = query_scalar(
            conn,
            f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id = {_p(conn)} "
            f"AND status IN ({terminal_success_sql})",
            (eid,),
        ) or 0

        # Integration simulation status
        sim_display = "MISSING"
        try:
            sim_row = query_one(
                conn,
                f"SELECT result FROM epic_simulations WHERE epic_id = {_p(conn)} "
                "AND phase = 'integration' "
                "ORDER BY created_at DESC LIMIT 1",
                (eid,),
            )
            if sim_row is not None:
                sim_display = sim_row["result"] or "UNKNOWN"
        except Exception:
            # Table may not exist or query may fail
            pass

        lines.append(f"## Epic YOK-{eid}: {item_title}")
        lines.append(f"Status: {item_status} | Tasks: {done_tasks}/{total_tasks} completed | Simulation: {sim_display}")
        lines.append("")

        # --- Branch table ---
        lines.append("### Branches")
        lines.append("| Branch | Commits Ahead | Worktree | Dirty State |")
        lines.append("|--------|---------------|----------|-------------|")

        for wt in worktrees:
            if not _branch_exists(repo_root, wt):
                continue

            ahead = _commits_ahead(repo_root, wt)
            wt_path = _worktree_path_for_branch(repo_root, wt)

            if wt_path and os.path.isdir(wt_path):
                dirty = _worktree_dirty_files(wt_path)
                if dirty:
                    dirty_state = f"dirty ({len(dirty)} files)"
                else:
                    dirty_state = "clean"
                wt_display = wt_path
            else:
                dirty_state = "no worktree"
                wt_display = "--"

            lines.append(f"| {wt} | {ahead} | {wt_display} | {dirty_state} |")

        lines.append("")

        # --- Incomplete tasks ---
        incomplete_rows = query_rows(
            conn,
            f"SELECT task_num, title, status FROM epic_tasks "
            f"WHERE epic_id = {_p(conn)} AND status NOT IN ({terminal_success_sql}) "
            f"ORDER BY task_num",
            (eid,),
        )
        if incomplete_rows:
            lines.append("### Incomplete Tasks")
            for row in incomplete_rows:
                lines.append(f"- Task {row['task_num']}: {row['title']} (status: {row['status']})")
            lines.append("")

        # --- Warnings ---
        warnings: List[str] = []

        # All tasks done but item not done
        if done_tasks == total_tasks and total_tasks > 0 and item_status != "done":
            warnings.append(
                f"- YOK-{eid}: All tasks completed but item is `{item_status}`. "
                f"Run `/yoke usher YOK-{eid}` to merge and complete."
            )
            warning_count += 1

        # Simulation missing
        if sim_display == "MISSING":
            warnings.append(
                f"- Integration simulation missing. Run `/yoke simulate {eid}` before merging."
            )
            warning_count += 1

        if warnings:
            lines.append("### Warnings")
            lines.extend(warnings)
            lines.append("")

        # --- Recommended merge order ---
        lines.append("### Recommended Merge Order")
        order_num = 0
        for wt in worktrees:
            if not _branch_exists(repo_root, wt):
                continue
            order_num += 1
            ahead = _commits_ahead(repo_root, wt)
            lines.append(f"{order_num}. {wt} ({ahead} commits)")
        lines.append("")

        lines.append("---")
        lines.append("")


    has_standalone = False

    if epic_filter is None:
        sun_branches = _list_sun_branches(repo_root)
        for ibranch in sun_branches:
            m = re.match(r"^YOK-(\d+)$", ibranch)
            if not m:
                continue
            isun = int(m.group(1))

            istatus = query_scalar(
                conn, f"SELECT status FROM items WHERE id = {_p(conn)}", (isun,)
            )
            if istatus != "done":
                continue

            if not has_standalone:
                lines.append("## Standalone Issue Branches")
                lines.append("| Branch | Item | Status | Commits Ahead |")
                lines.append("|--------|------|--------|---------------|")
                has_standalone = True

            ititle = query_scalar(
                conn, f"SELECT title FROM items WHERE id = {_p(conn)}", (isun,)
            ) or ""
            iahead = _commits_ahead(repo_root, ibranch)
            lines.append(f"| {ibranch} | YOK-{isun}: {ititle} | {istatus} | {iahead} |")

        if has_standalone:
            lines.append("")
            lines.append("---")
            lines.append("")


    all_ready_branches: List[str] = []
    for eid in epic_ids:
        wt_rows = query_rows(conn, _epic_worktrees_sql(conn), (eid,))
        for r in wt_rows:
            wt = r["worktree"]
            if _branch_exists(repo_root, wt) and wt not in all_ready_branches:
                all_ready_branches.append(wt)

    has_conflicts = False

    if all_ready_branches and _has_merge_tree(repo_root):
        checked: set = set()
        for branch_index, left_branch in enumerate(all_ready_branches):
            for right_branch in all_ready_branches[branch_index + 1:]:
                pair = frozenset((left_branch, right_branch))
                if pair in checked:
                    continue
                checked.add(pair)

                conflict_files = _check_conflict(
                    repo_root, left_branch, right_branch,
                )
                if conflict_files:
                    if not has_conflicts:
                        lines.append("## Potential Conflicts")
                        has_conflicts = True
                    file_list = ", ".join(conflict_files)
                    lines.append(
                        f"- {left_branch} vs {right_branch}: {file_list}",
                    )

        if has_conflicts:
            lines.append("")
    elif all_ready_branches and not _has_merge_tree(repo_root):
        lines.append("## Potential Conflicts")
        lines.append("*Skipped: `git merge-tree --write-tree` not available (requires Git 2.38+).*")
        lines.append("")


    lines.append("## Summary")

    total_branches = 0
    total_ready = 0
    total_blocked = 0

    for eid in epic_ids:
        wt_rows = query_rows(conn, _epic_worktrees_sql(conn), (eid,))
        for r in wt_rows:
            wt = r["worktree"]
            if not _branch_exists(repo_root, wt):
                continue
            total_branches += 1
            wt_total = query_scalar(
                conn,
                f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id = {_p(conn)} "
                f"AND worktree = {_p(conn)}",
                (eid, wt),
            ) or 0
            wt_done = query_scalar(
                conn,
                f"SELECT COUNT(*) FROM epic_tasks WHERE epic_id = {_p(conn)} "
                f"AND worktree = {_p(conn)} "
                f"AND status IN ({terminal_success_sql})",
                (eid, wt),
            ) or 0
            if wt_done == wt_total:
                total_ready += 1
            else:
                total_blocked += 1

    lines.append(f"- Ready to merge: {total_ready} branches")
    if total_blocked > 0:
        lines.append(f"- Blocked: {total_blocked} branches (incomplete tasks)")
    lines.append(f"- Warnings: {warning_count}")
    if has_conflicts:
        lines.append("- Conflicts detected: see above")
    else:
        lines.append("- Conflicts detected: 0")

    # Report if no content found
    if not has_epic_content and not has_standalone:
        lines.append("")
        if epic_filter is not None:
            lines.append(f"No unmerged branches found for epic {epic_filter}.")
        else:
            lines.append("No unmerged epic or standalone issue branches found.")

    conn.close()
    return "\n".join(lines) + "\n"
