"""Markdown report generation for merge readiness audits."""

from __future__ import annotations

import os
from typing import List

from yoke_core.engines import merge_audit_report_helpers as facts
from yoke_core.engines.merge_audit_report_helpers import _parent


def generate_report(
    epic_filter: str | None = None, *, project: str | None = None
) -> str:
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
    _check_conflict = ma._check_conflict
    _now_iso = ma._now_iso

    snapshot = facts.load_snapshot(epic_filter, project=project)
    epics = snapshot["epics"]
    repo_root = _resolve_repo_root()

    lines: List[str] = []
    lines.append("# Merge Readiness Audit")
    lines.append(f"Generated: {_now_iso()}")
    lines.append("")

    has_epic_content = False
    warning_count = 0

    for epic in epics:
        item_title = epic["title"]
        item_status = epic["status"]
        epic_ref = epic["public_ref"]
        worktrees = list(epic["branches"])

        # Check if any branches still exist (unmerged)
        has_branches = any(_branch_exists(repo_root, wt) for wt in worktrees)
        if not has_branches:
            continue

        has_epic_content = True

        total_tasks = epic["total"]
        done_tasks = epic["done"]
        sim_display = epic["simulation"]

        lines.append(f"## Epic {epic_ref}: {item_title}")
        lines.append(
            f"Status: {item_status} | Tasks: {done_tasks}/{total_tasks} completed | Simulation: {sim_display}"
        )
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
        incomplete_rows = epic["incomplete"]
        if incomplete_rows:
            lines.append("### Incomplete Tasks")
            for row in incomplete_rows:
                lines.append(
                    f"- Task {row['task_num']}: {row['title']} (status: {row['status']})"
                )
            lines.append("")

        # --- Warnings ---
        warnings: List[str] = []

        # All tasks done but item not done
        if done_tasks == total_tasks and total_tasks > 0 and item_status != "done":
            warnings.append(
                f"- {epic_ref}: All tasks completed but item is `{item_status}`. "
                f"Run `/yoke usher {epic_ref}` to merge and complete."
            )
            warning_count += 1

        # Simulation missing
        if sim_display == "MISSING":
            warnings.append(
                f"- Integration simulation missing. Run `/yoke simulate {epic_ref}` before merging."
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
        standalone_rows = snapshot["standalone"]
        for standalone in standalone_rows:
            ibranch = str(standalone["branch"])
            if not _branch_exists(repo_root, ibranch):
                continue
            istatus = str(standalone["status"])

            if not has_standalone:
                lines.append("## Standalone Issue Branches")
                lines.append("| Branch | Item | Status | Commits Ahead |")
                lines.append("|--------|------|--------|---------------|")
                has_standalone = True

            ititle = str(standalone["title"] or "")
            iahead = _commits_ahead(repo_root, ibranch)
            iref = standalone["public_ref"]
            lines.append(f"| {ibranch} | {iref}: {ititle} | {istatus} | {iahead} |")

        if has_standalone:
            lines.append("")
            lines.append("---")
            lines.append("")

    all_ready_branches: List[str] = []
    for epic in epics:
        for wt in epic["branches"]:
            if _branch_exists(repo_root, wt) and wt not in all_ready_branches:
                all_ready_branches.append(wt)

    has_conflicts = False

    if all_ready_branches and _has_merge_tree(repo_root):
        checked: set = set()
        for branch_index, left_branch in enumerate(all_ready_branches):
            for right_branch in all_ready_branches[branch_index + 1 :]:
                pair = frozenset((left_branch, right_branch))
                if pair in checked:
                    continue
                checked.add(pair)

                conflict_files = _check_conflict(
                    repo_root,
                    left_branch,
                    right_branch,
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
        lines.append(
            "*Skipped: `git merge-tree --write-tree` not available (requires Git 2.38+).*"
        )
        lines.append("")

    lines.append("## Summary")

    total_branches = 0
    total_ready = 0
    total_blocked = 0

    for epic in epics:
        for wt, counts in epic["branches"].items():
            if not _branch_exists(repo_root, wt):
                continue
            total_branches += 1
            if counts["done"] == counts["total"]:
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

    return "\n".join(lines) + "\n"
