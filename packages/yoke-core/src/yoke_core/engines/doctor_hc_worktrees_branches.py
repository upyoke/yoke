"""Branch divergence and stale-remote-branch health checks.

Cluster: HC-branch-divergence (local vs origin/main divergence) and
HC-stale-remote-branches (remote branches matching done/cancelled items).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project_id

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)


def hc_branch_divergence(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-branch-divergence: Local/remote branch divergence."""
    issues: List[str] = []

    # Determine default branch
    default_branch = None
    for candidate in ("main", "master"):
        r = _base._run(["git", "rev-parse", "--verify", candidate])
        if r.returncode == 0:
            default_branch = candidate
            break

    if default_branch:
        _base._run(["git", "fetch", "origin", default_branch], timeout=15)
        local_r = _base._run(["git", "rev-parse", default_branch])
        remote_r = _base._run(["git", "rev-parse", f"origin/{default_branch}"])
        local_head = local_r.stdout.strip() if local_r.returncode == 0 else ""
        remote_head = remote_r.stdout.strip() if remote_r.returncode == 0 else ""

        if local_head and remote_head and local_head != remote_head:
            ahead_r = _base._run(["git", "rev-list", f"origin/{default_branch}..{default_branch}", "--count"])
            behind_r = _base._run(["git", "rev-list", f"{default_branch}..origin/{default_branch}", "--count"])
            ahead = ahead_r.stdout.strip() if ahead_r.returncode == 0 else "?"
            behind = behind_r.stdout.strip() if behind_r.returncode == 0 else "?"
            issues.append(
                f"- local {default_branch} diverged from origin/{default_branch}: "
                f"{ahead} ahead, {behind} behind"
            )
            issues.append(
                f"- To fix: `git rebase origin/{default_branch} && "
                f"git push origin {default_branch}`"
            )

    if issues:
        rec.record("HC-branch-divergence", "Local/remote branch divergence", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-branch-divergence", "Local/remote branch divergence", "PASS", "")


def hc_stale_remote_branches(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-remote-branches: Stale remote branches."""
    issues: List[str] = []
    fixed = 0
    fix_failed = 0

    # Get project repos
    projects: List[dict] = []
    if _base._table_exists(conn, "projects"):
        projects = [
            {
                "id": row["id"],
                "slug": row["slug"],
                "checkout": checkout_for_project_id(int(row["id"])),
            }
            for row in query_rows(conn, "SELECT id, slug FROM projects ORDER BY id")
        ]

    repo_root = _base._resolve_repo_root()
    yoke_root = str(Path(repo_root) / "data") if repo_root else ""

    # Cache remote branches for each project
    remote_caches: Dict[str, set] = {}
    for proj in projects:
        pid = proj["slug"]
        rpath = proj["checkout"]
        if not rpath or not Path(rpath).is_dir():
            continue
        lr = _base._run(["git", "-C", rpath, "ls-remote", "--heads", "origin"], timeout=15)
        branches = set()
        if lr.returncode == 0:
            for line in lr.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    ref = parts[1]
                    if ref.startswith("refs/heads/"):
                        branches.add(ref[len("refs/heads/"):])
        remote_caches[pid] = branches

    # Default repo cache
    default_branches: set = set()
    if repo_root:
        lr = _base._run(["git", "-C", repo_root, "ls-remote", "--heads", "origin"], timeout=15)
        if lr.returncode == 0:
            for line in lr.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    ref = parts[1]
                    if ref.startswith("refs/heads/"):
                        default_branches.add(ref[len("refs/heads/"):])

    # Check done/cancelled items
    done_rows = query_rows(
        conn,
        "SELECT i.id, i.type, COALESCE(p.slug, '') as project FROM items i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE i.status IN ('done', 'cancelled')",
    )
    for row in done_rows:
        did = row["id"]
        proj = row["project"]
        pattern = f"YOK-{did}"

        # Resolve cache and repo
        cache = default_branches
        target_repo = repo_root or ""
        if proj and proj != "null" and proj in remote_caches:
            cache = remote_caches[proj]
            for p in projects:
                if p["slug"] == proj:
                    rp = p["checkout"]
                    if rp and Path(rp).is_dir():
                        target_repo = str(rp)
                    break

        if pattern not in cache:
            continue

        proj_label = f" [{proj}]" if proj and proj != "null" and proj != "yoke" else ""

        if args.fix:
            dr = _base._run(["git", "-C", target_repo, "push", "origin", "--delete", pattern],
                       timeout=15)
            if dr.returncode == 0:
                fixed += 1
                issues.append(
                    f"- Fixed: deleted stale remote branch {pattern}{proj_label} "
                    f"-- YOK-{did} is done/cancelled"
                )
            else:
                fix_failed += 1
                issues.append(
                    f"- FAILED to delete stale remote branch {pattern}{proj_label} "
                    f"-- YOK-{did} is done/cancelled "
                    f"(git -C {target_repo} push origin --delete {pattern})"
                )
        else:
            issues.append(
                f"- Stale remote branch: {pattern}{proj_label} "
                f"-- YOK-{did} is done/cancelled "
                f"(git push origin --delete {pattern})"
            )

    if issues:
        if args.fix:
            summary = f"- --fix: deleted {fixed} stale remote branch(es)"
            if fix_failed > 0:
                summary += f", {fix_failed} failed"
                rec.record("HC-stale-remote-branches", "Stale remote branches", "WARN",
                            summary + "\n" + "\n".join(issues))
            else:
                rec.record("HC-stale-remote-branches", "Stale remote branches", "PASS",
                            summary + "\n" + "\n".join(issues))
        else:
            rec.record("HC-stale-remote-branches", "Stale remote branches", "WARN",
                        "\n".join(issues))
    else:
        rec.record("HC-stale-remote-branches", "Stale remote branches", "PASS", "")
