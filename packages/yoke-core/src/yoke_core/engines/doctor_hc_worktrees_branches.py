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
from yoke_core.engines import merge_worktree_safe_prune as _safe_prune
from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
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
    preserved = 0

    # Get project repos
    projects: List[dict] = []
    if _base._table_exists(conn, "projects"):
        projects = [
            {
                "id": row["id"],
                "slug": row["slug"],
                "checkout": checkout_for_project_id(int(row["id"])),
                "default_branch": str(row["default_branch"] or "main"),
            }
            for row in query_rows(
                conn,
                "SELECT id, slug, default_branch FROM projects ORDER BY id",
            )
        ]

    repo_root = _base._resolve_repo_root()

    # Cache each successfully inspected project's branches with the exact
    # checkout and integration target. A missing project checkout must never
    # fall back to a different repository merely because both use YOK-N refs.
    remote_caches: Dict[str, tuple[set[str], str, str]] = {}
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
            remote_caches[pid] = (
                branches,
                str(rpath),
                proj["default_branch"],
            )

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
            yoke_target = next(
                (
                    proj["default_branch"]
                    for proj in projects
                    if proj["slug"] == "yoke"
                ),
                "main",
            )
            remote_caches["yoke"] = (
                default_branches,
                str(repo_root),
                yoke_target,
            )

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

        # Resolve only the owning project's inspected checkout. Never use the
        # current/default repository for a different project's item.
        project_slug = proj if proj and proj != "null" else "yoke"
        context = remote_caches.get(project_slug)
        if context is None:
            continue
        cache, target_repo, target_branch = context

        if pattern not in cache:
            continue

        proj_label = f" [{proj}]" if proj and proj != "null" and proj != "yoke" else ""

        if args.fix:
            if _safe_prune.item_cleanup_authority_blocks_prune(conn, int(did)):
                preserved += 1
                issues.append(
                    f"- PRESERVED stale remote branch {pattern}{proj_label}: "
                    "cleanup authority is active or could not be proven idle"
                )
                continue

            result = delete_remote_branch_if_merged(
                run_git=lambda command: _base._run(
                    ["git", "-C", target_repo, *command],
                    timeout=15,
                ),
                branch=pattern,
                target_branch=target_branch,
            )
            if result.cleanup_complete:
                fixed += 1
                if result.status == "deleted":
                    issues.append(
                        f"- Fixed: deleted stale remote branch "
                        f"{pattern}{proj_label} -- YOK-{did} is done/cancelled"
                    )
                else:
                    issues.append(
                        f"- Fixed: stale remote branch {pattern}{proj_label} "
                        "was already absent"
                    )
            else:
                preserved += 1
                issues.append(
                    f"- PRESERVED stale remote branch {pattern}{proj_label}: "
                    f"{result.reason}"
                )
        else:
            issues.append(
                f"- Stale remote branch: {pattern}{proj_label} "
                f"-- YOK-{did} is done/cancelled "
                "(rerun this check with --fix for proof-gated cleanup)"
            )

    if issues:
        if args.fix:
            summary = f"- --fix: deleted {fixed} stale remote branch(es)"
            if preserved > 0:
                summary += f", {preserved} preserved"
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
