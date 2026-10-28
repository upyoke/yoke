"""Branch divergence and stale-remote-branch health checks.

Cluster: HC-branch-divergence (local vs origin/main divergence) and
HC-stale-remote-branches (remote branches matching done/cancelled items).
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project_id

import yoke_core.engines.doctor_report as _base

from yoke_cli.config import credentialed_git as _credentialed_git

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)
from yoke_core.engines.merge_prune_authority import (
    item_cleanup_authority_blocks_prune,
)
from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
)

# A credentialed remote read either authenticates or refuses by name, so the
# bound is a slow network rather than the wait for a prompt nobody answers.
# The old 15s ceiling was short enough that an unauthenticated fetch read as
# a hang instead of the failure it was.
_REMOTE_READ_TIMEOUT = 60


def _reason(result) -> str:
    """The first meaningful line of a failed git result."""
    detail = (result.stderr or result.stdout or "").strip()
    return detail.splitlines()[0] if detail else f"exit {result.returncode}"


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
        fetched = _credentialed_git.run(
            ["fetch", "origin", default_branch],
            timeout=_REMOTE_READ_TIMEOUT,
        )
        if fetched.returncode != 0:
            issues.append(f"- could not reach origin: {_reason(fetched)}")
        local_r = _base._run(["git", "rev-parse", default_branch])
        remote_r = _base._run(["git", "rev-parse", f"origin/{default_branch}"])
        local_head = local_r.stdout.strip() if local_r.returncode == 0 else ""
        remote_head = remote_r.stdout.strip() if remote_r.returncode == 0 else ""

        if local_head and remote_head and local_head != remote_head:
            ahead_r = _base._run(
                [
                    "git",
                    "rev-list",
                    f"origin/{default_branch}..{default_branch}",
                    "--count",
                ]
            )
            behind_r = _base._run(
                [
                    "git",
                    "rev-list",
                    f"{default_branch}..origin/{default_branch}",
                    "--count",
                ]
            )
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
        rec.record(
            "HC-branch-divergence",
            "Local/remote branch divergence",
            "WARN",
            "\n".join(issues),
        )
    else:
        rec.record("HC-branch-divergence", "Local/remote branch divergence", "PASS", "")


def hc_stale_remote_branches(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stale-remote-branches: Stale remote branches."""
    issues: List[str] = []
    fixed = 0
    preserved = 0

    projects = query_rows(
        conn,
        "SELECT id, slug, default_branch FROM projects "
        "WHERE (%s = '' OR slug = %s OR CAST(id AS TEXT) = %s) ORDER BY id",
        (str(args.project or ""),) * 3,
    )
    inspected = 0
    for project in projects:
        repo = checkout_for_project_id(int(project["id"]))
        if not repo or not Path(repo).is_dir():
            continue
        inspected += 1
        target = str(project["default_branch"] or "main")

        def run_git(command):
            return _credentialed_git.run(
                ["-C", str(repo), *command], timeout=_REMOTE_READ_TIMEOUT
            )

        listed = run_git(["ls-remote", "--heads", "origin"])
        if listed.returncode != 0:
            preserved += 1
            issues.append(
                f"- remote_branch_read_failed [{project['slug']}]: "
                f"{_reason(listed)}; restore origin access and rerun this check"
            )
            continue
        branches = {}
        for line in listed.stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].startswith("refs/heads/"):
                branches[fields[1][len("refs/heads/") :]] = fields[0]
        if not branches:
            continue
        rows = query_rows(
            conn,
            "WITH matches AS ("
            "SELECT item_id, public_ref AS branch FROM item_refs "
            "WHERE public_ref = ANY(%s) "
            "UNION SELECT item_id, branch FROM item_worktrees "
            "WHERE branch = ANY(%s)) "
            "SELECT i.id, i.status, r.public_ref, m.branch, "
            "EXISTS (SELECT 1 FROM item_worktrees w WHERE w.item_id = i.id "
            "AND w.state = 'active') AS has_worktree "
            "FROM matches m JOIN items i ON i.id = m.item_id "
            "JOIN item_refs r ON r.item_id = i.id "
            "WHERE i.project_id = %s ORDER BY i.id, m.branch",
            (list(branches), list(branches), project["id"]),
        )
        fetched = False
        for row in rows:
            if row["status"] not in {"done", "cancelled"}:
                continue
            branch = row["branch"]
            label = f"{branch} [{project['slug']}]"
            if row["has_worktree"]:
                preserved += 1
                issues.append(f"- PRESERVED {label}: lane sweep owns it")
                continue
            if not args.fix:
                issues.append(
                    f"- Stale remote branch: {label} -- {row['public_ref']} "
                    "is done/cancelled (rerun this check with --fix "
                    "for proof-gated cleanup)"
                )
                continue
            if item_cleanup_authority_blocks_prune(conn, int(row["id"])):
                preserved += 1
                issues.append(
                    f"- PRESERVED stale remote branch {label}: "
                    "cleanup authority is active or could not be proven idle"
                )
                continue
            if not fetched:
                fetch = run_git(
                    ["fetch", "origin", "+refs/heads/*:refs/remotes/origin/*"]
                )
                if fetch.returncode != 0:
                    preserved += 1
                    issues.append(
                        f"- remote_branch_fetch_failed [{project['slug']}]: "
                        f"{_reason(fetch)}; restore origin access and rerun with --fix"
                    )
                    break
                fetched = True
            result = delete_remote_branch_if_merged(
                run_git=run_git,
                branch=branch,
                target_branch=target,
                refreshed_branches=branches,
            )
            if result.cleanup_complete:
                fixed += 1
                issues.append(f"- Fixed: {label}: {result.reason}")
            else:
                preserved += 1
                issues.append(
                    f"- PRESERVED stale remote branch {label}: {result.reason}"
                )

    if not inspected:
        rec.record(
            "HC-stale-remote-branches",
            "Stale remote branches",
            "N/A",
            "this runner has no checkout for it",
        )
        return

    if issues:
        if args.fix:
            summary = f"- --fix: deleted {fixed} stale remote branch(es)"
            if preserved > 0:
                summary += f", {preserved} preserved"
                rec.record(
                    "HC-stale-remote-branches",
                    "Stale remote branches",
                    "WARN",
                    summary + "\n" + "\n".join(issues),
                )
            else:
                rec.record(
                    "HC-stale-remote-branches",
                    "Stale remote branches",
                    "PASS",
                    summary + "\n" + "\n".join(issues),
                )
        else:
            rec.record(
                "HC-stale-remote-branches",
                "Stale remote branches",
                "WARN",
                "\n".join(issues),
            )
    else:
        rec.record("HC-stale-remote-branches", "Stale remote branches", "PASS", "")
