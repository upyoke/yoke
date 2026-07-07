"""Worktree and Git health checks — main checkout, discoveries, stashes, contamination.

GitHub issue and project-specific checks live in doctor_hc_worktrees_gh.py.
Worktree-health (uncommitted/stale entries) lives in doctor_hc_worktrees_health.py.
Branch divergence and stale remote branches live in doctor_hc_worktrees_branches.py.

GitHub auth + repo resolution is delegated to the canonical resolver
:mod:`yoke_core.domain.project_github_auth`. Sibling HCs call
``subprocess.run([...], env=resolve_project_github_auth(project).env)``
directly and translate ``ProjectGithubAuthError`` to FAIL records with
operator-facing repair hints.

HC functions hosted here: HC-main-checkout, HC-uncaptured-discoveries,
HC-orphaned-stashes, HC-cross-project-commits.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

# Re-export HCs from sibling clusters so doctor.py keeps a single import block.
from yoke_core.engines.doctor_hc_worktrees_health import (  # noqa: F401
    hc_worktree_health,
)
from yoke_core.engines.doctor_hc_worktrees_branches import (  # noqa: F401
    hc_branch_divergence,
    hc_stale_remote_branches,
)


# Slugs for delegated sync HCs (dispatched to resync engine)
_DELEGATED_SYNC_HCS = [
    "missing-gh-issues", "orphan-epic-tasks", "title-drift", "body-drift",
    "reverse-completeness", "comment-sync", "label-drift", "state-drift",
    "frozen-label-drift", "blocked-label-drift", "task-label-drift",
]


def _pat_configured(project: str = "yoke", db_path=None) -> bool:
    """Return True when the project PAT capability resolves successfully.

    GitHub doctor HCs SKIP via
    :data:`doctor_hc_gh_skip.GH_PAT_NOT_CONFIGURED_SKIP_REASON` when this
    returns False; there is no host-``gh`` fallback.
    """
    try:
        resolve_project_github_auth(project, db_path=db_path)
    except ProjectGithubAuthError:
        return False
    return True


def hc_main_checkout(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-main-checkout: Main repo branch checkout."""
    issues: List[str] = []
    main_root = _base._resolve_main_root()
    if not main_root:
        issues.append("- Could not resolve main repo root to check branch")
    else:
        git_dir = Path(main_root) / ".git"
        if not git_dir.exists():
            # Not a git directory, pass silently
            rec.record("HC-main-checkout", "Main repo branch checkout", "PASS", "")
            return
        r = _base._run(["git", "-C", main_root, "rev-parse", "--abbrev-ref", "HEAD"])
        branch = r.stdout.strip() if r.returncode == 0 else ""
        if not branch:
            issues.append(f"- Could not determine current branch of main repo at {main_root}")
        elif branch == "HEAD":
            issues.append(
                f"- Main repo at {main_root} is in detached HEAD state. "
                "All bookkeeping commits will land on a detached HEAD instead of main. "
                f"Run: git -C {main_root} checkout main"
            )
        elif branch not in ("main", "master"):
            issues.append(
                f"- Local repo is checked out to '{branch}'. "
                "All bookkeeping commits will land on this branch instead of main. "
                "Run: git checkout main"
            )

    if issues:
        rec.record("HC-main-checkout", "Main repo branch checkout", "WARN", "\n".join(issues))
    else:
        rec.record("HC-main-checkout", "Main repo branch checkout", "PASS", "")



def hc_uncaptured_discoveries(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-uncaptured-discoveries: Uncaptured discoveries in recent commits."""
    issues: List[str] = []
    discovery_pattern = re.compile(
        r"bug|broken|gap|missing|fails when|error|wrong|crash|hack|workaround|hotfix",
        re.IGNORECASE,
    )
    sun_pattern = re.compile(r"YOK-\d+")

    r = _base._run(["git", "log", "--oneline", "-20"])
    if r.returncode == 0:
        for line in r.stdout.strip().splitlines():
            if not line:
                continue
            if discovery_pattern.search(line) and not sun_pattern.search(line):
                issues.append(f"- Commit without YOK-N reference: {line}")

    if issues:
        rec.record("HC-uncaptured-discoveries", "Uncaptured discoveries", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-uncaptured-discoveries", "Uncaptured discoveries", "PASS", "")



def hc_orphaned_stashes(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-orphaned-stashes: Orphaned pre-merge stashes."""
    issues: List[str] = []
    r = _base._run(["git", "stash", "list"])
    if r.returncode == 0 and r.stdout.strip():
        for line in r.stdout.strip().splitlines():
            if "yoke-pre-rebase-" in line:
                issues.append(f"- {line}")

    if issues:
        detail = "Orphaned pre-merge stashes found:\n" + "\n".join(issues)
        rec.record("HC-orphaned-stashes", "Orphaned pre-merge stashes", "WARN", detail)
    else:
        rec.record("HC-orphaned-stashes", "Orphaned pre-merge stashes", "PASS", "")



def hc_cross_project_commits(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-cross-project-commits: Cross-project commit contamination."""
    issues: List[str] = []
    bookkeeping = {
        "ouroboros/", ".agents/", ".claude/",
    }
    min_commit_date = _base._read_str_cutoff("hc_cross_project_commits_min_commit_date")

    # Get done items with non-yoke projects
    rows = query_rows(
        conn,
        "SELECT i.id, p.slug AS project FROM items i "
        "JOIN projects p ON p.id = i.project_id "
        "WHERE i.status='done' AND p.slug <> 'yoke'",
    )
    for row in rows:
        item_id = row["id"]
        project = row["project"]
        # Find commits on base branch referencing this item
        log_cmd = ["git", "log", "main", "--oneline", f"--grep=YOK-{item_id}", "--format=%H"]
        if min_commit_date:
            log_cmd.append(f"--since={min_commit_date}")
        cr = _base._run(log_cmd)
        if cr.returncode != 0 or not cr.stdout.strip():
            continue
        item_bad: List[str] = []
        for commit_hash in cr.stdout.strip().splitlines():
            if not commit_hash:
                continue
            fr = _base._run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash])
            if fr.returncode != 0:
                continue
            for fname in fr.stdout.strip().splitlines():
                if not fname:
                    continue
                # Skip bookkeeping files
                is_bookkeeping = False
                for bk in bookkeeping:
                    if bk.endswith("/"):
                        if fname.startswith(bk):
                            is_bookkeeping = True
                            break
                    elif fname == bk:
                        is_bookkeeping = True
                        break
                if not is_bookkeeping:
                    short = commit_hash[:10]
                    item_bad.append(f"  - commit {short}: {fname}")
        if item_bad:
            issues.append(
                f"- YOK-{item_id} (project={project}):\n" + "\n".join(item_bad)
            )

    if issues:
        rec.record("HC-cross-project-commits", "Cross-project commit contamination", "WARN",
                    "\n".join(issues))
    else:
        rec.record("HC-cross-project-commits", "Cross-project commit contamination", "PASS", "")
