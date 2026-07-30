"""Worktree health check — uncommitted/stale/orphaned worktrees and branches.

Cluster: HC-worktree-health (single HC). Inspects ``git worktree list``,
the configured ``.worktrees`` directory, local YOK-* branches, and the
universal ``item_worktrees`` registry to detect stale terminal-item lanes.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def hc_worktree_health(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-worktree-health: Worktree health."""
    issues: List[str] = []

    # Parse git worktree list --porcelain
    r = _base._run(["git", "worktree", "list", "--porcelain"])
    if r.returncode != 0:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
        return

    entries: List[dict] = []
    current: dict = {}
    for line in r.stdout.splitlines():
        if line.startswith("worktree "):
            current = {"path": line[len("worktree "):]}
        elif line.startswith("branch "):
            branch = line[len("branch "):]
            if branch.startswith("refs/heads/"):
                branch = branch[len("refs/heads/"):]
            current["branch"] = branch
        elif line == "":
            if current:
                entries.append(current)
            current = {}
    if current:
        entries.append(current)

    registered_paths = {e.get("path", "") for e in entries}

    for entry in entries:
        wt_path = entry.get("path", "")
        branch = entry.get("branch", "")
        if branch in ("main", "master") or not wt_path:
            continue

        # Check for dirty worktree
        if Path(wt_path).is_dir():
            dr = _base._run(
                [
                    "git",
                    "-C",
                    wt_path,
                    "status",
                    "--porcelain",
                    "--ignored=matching",
                    "--untracked-files=all",
                ]
            )
            if dr.returncode == 0 and dr.stdout.strip():
                issues.append(
                    f"- Worktree {branch} at {wt_path} has uncommitted changes "
                    f"(cd {wt_path} && git status)"
                )

        # Check terminal ownership through the universal registry.
        p = _p(conn)
        owners = query_rows(
            conn,
            "SELECT DISTINCT iw.item_id, i.status FROM item_worktrees iw "
            "JOIN items i ON i.id = iw.item_id "
            f"WHERE iw.branch = {p} OR iw.path = {p}",
            (branch, wt_path),
        )
        for owner in owners:
            if owner["status"] in ("done", "cancelled"):
                issues.append(
                    f"- Stale worktree: {branch} at {wt_path} "
                    f"— {render_item_ref(conn, owner['item_id'])} is {owner['status']} "
                    "(safe cleanup requires exact DB ownership, no active "
                    "claim, a clean tree, and target ancestry)"
                )

    # Check configured worktrees_dir for extra directories
    repo_root = _base._resolve_repo_root()
    if repo_root:
        wt_dir = Path(repo_root) / ".worktrees"
        if wt_dir.is_dir():
            for child in sorted(wt_dir.iterdir()):
                if not child.is_dir():
                    continue
                child_str = str(child)
                if child_str in registered_paths:
                    continue
                p = _p(conn)
                owners = query_rows(
                    conn,
                    "SELECT DISTINCT iw.item_id, i.status "
                    "FROM item_worktrees iw "
                    "JOIN items i ON i.id = iw.item_id "
                    f"WHERE iw.path = {p}",
                    (child_str,),
                )
                for owner in owners:
                    if owner["status"] in ("done", "cancelled"):
                        issues.append(
                            f"- Stale worktree directory: {child_str} "
                            f"— {render_item_ref(conn, owner['item_id'])} is {owner['status']} "
                            "(unregistered directory preserved for inspection)"
                        )

    # Detect stale local branches for done/cancelled items
    done_rows = query_rows(
        conn,
        "SELECT DISTINCT iw.item_id, iw.branch FROM item_worktrees iw "
        "JOIN items i ON i.id = iw.item_id "
        "WHERE i.status IN ('done', 'cancelled')",
    )
    for row in done_rows:
        did = row["item_id"]
        branch = row["branch"]
        br = _base._run(["git", "rev-parse", "--verify", branch])
        if br.returncode == 0:
            issues.append(
                f"- Stale local branch: {branch} "
                f"— {render_item_ref(conn, did)} is done/cancelled "
                "(safe pruning requires DB ownership, no active claim, and "
                "target ancestry)"
            )

    # Terminal updates release operational lanes but retain audit history.
    wt_rows = query_rows(
        conn,
        "SELECT i.id, iw.branch FROM items i "
        "JOIN item_worktrees iw ON iw.item_id = i.id "
        "WHERE i.status IN ('done', 'cancelled') AND iw.state = 'active'",
    )
    for row in wt_rows:
        issues.append(
            f"- Active worktree lane on terminal item: {render_item_ref(conn, row['id'])} "
            f"has branch='{row['branch']}' "
            "(release the lane while preserving its audit record)"
        )

    if issues:
        rec.record("HC-worktree-health", "Worktree health", "WARN", "\n".join(issues))
    else:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
