"""Worktree health check — uncommitted/stale/orphaned worktrees and branches.

Cluster: HC-worktree-health (single HC). Inspects ``git worktree list``,
the configured ``.worktrees`` directory, local YOK-* branches, and the
``items.worktree`` DB field to detect stale entries for done/cancelled items.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows

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
            dr = _base._run(["git", "-C", wt_path, "status", "--porcelain"])
            if dr.returncode == 0 and dr.stdout.strip():
                issues.append(
                    f"- Worktree {branch} at {wt_path} has uncommitted changes "
                    f"(cd {wt_path} && git status)"
                )

        # Check for stale worktrees (done/cancelled items)
        m = re.search(r"[Yy][Oo][Kk]-(\d+)", branch)
        if m:
            yok_id = int(m.group(1))
            p = _p(conn)
            row = query_rows(
                conn,
                f"SELECT status FROM items WHERE id={p}",
                (yok_id,),
            )
            if row and row[0]["status"] in ("done", "cancelled"):
                status = row[0]["status"]
                issues.append(
                    f"- Stale worktree: {branch} at {wt_path} "
                    f"— YOK-{yok_id} is {status} "
                    f"(git worktree remove {wt_path} && git branch -D {branch})"
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
                m = re.search(r"[Yy][Oo][Kk]-(\d+)", child.name)
                if m:
                    yok_id = int(m.group(1))
                    p = _p(conn)
                    row = query_rows(
                        conn,
                        f"SELECT status FROM items WHERE id={p}",
                        (yok_id,),
                    )
                    if row and row[0]["status"] in ("done", "cancelled"):
                        status = row[0]["status"]
                        issues.append(
                            f"- Stale worktree directory: {child_str} "
                            f"— YOK-{yok_id} is {status} "
                            f"(rm -rf {child_str})"
                        )

    # Detect stale local branches for done/cancelled items
    done_rows = query_rows(
        conn,
        "SELECT id FROM items WHERE status IN ('done', 'cancelled')",
    )
    for row in done_rows:
        did = row["id"]
        br = _base._run(["git", "rev-parse", "--verify", f"YOK-{did}"])
        if br.returncode == 0:
            issues.append(
                f"- Stale local branch: YOK-{did} "
                f"— YOK-{did} is done/cancelled "
                f"(git branch -D YOK-{did})"
            )

    # Detect non-null worktree DB field on done/cancelled items
    wt_rows = query_rows(
        conn,
        "SELECT id, worktree FROM items "
        "WHERE status IN ('done', 'cancelled') "
        "AND worktree IS NOT NULL AND worktree <> ''",
    )
    for row in wt_rows:
        issues.append(
            f"- Non-null worktree DB field on done item: YOK-{row['id']} "
            f"has worktree='{row['worktree']}' "
            f"(python3 -m yoke_core.cli.db_router items update {row['id']} worktree '')"
        )

    if issues:
        rec.record("HC-worktree-health", "Worktree health", "WARN", "\n".join(issues))
    else:
        rec.record("HC-worktree-health", "Worktree health", "PASS", "")
