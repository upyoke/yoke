"""Merge readiness audit engine public facade."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from yoke_core.domain.worktree import resolve_main_root

def _resolve_repo_root() -> str:
    """Resolve the main repo root (not a worktree)."""
    env = os.environ.get("MERGE_AUDIT_REPO_ROOT")
    if env:
        return env

    try:
        return resolve_main_root()
    except RuntimeError:
        pass

    # Fallback: walk up from this file
    from yoke_core.api.repo_root import find_repo_root

    repo_root = find_repo_root(Path(__file__))
    if (repo_root / ".git").exists():
        return str(repo_root)

    raise RuntimeError("Cannot resolve main repo root")


def _branch_exists(repo_root: str, branch: str) -> bool:
    """Check if a local branch exists."""
    result = subprocess.run(
        ["git", "-C", repo_root, "rev-parse", "--verify", f"refs/heads/{branch}"],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0


def _commits_ahead(repo_root: str, branch: str) -> int:
    """Count commits ahead of main for a branch."""
    result = subprocess.run(
        ["git", "-C", repo_root, "rev-list", "--count", f"main..{branch}"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode == 0:
        try:
            return int(result.stdout.strip())
        except ValueError:
            pass
    return 0


def _worktree_path_for_branch(repo_root: str, branch: str) -> Optional[str]:
    """Get the worktree path for a given branch, if any."""
    result = subprocess.run(
        ["git", "-C", repo_root, "worktree", "list", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return None

    wt_path = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            wt_path = line[len("worktree "):]
        elif line.startswith("branch refs/heads/"):
            wt_branch = line[len("branch refs/heads/"):]
            if wt_branch == branch:
                return wt_path
    return None


def _worktree_dirty_files(wt_path: str) -> List[str]:
    """Return list of dirty file lines in the worktree, or empty list."""
    if not os.path.isdir(wt_path):
        return []
    result = subprocess.run(
        ["git", "-C", wt_path, "status", "--porcelain"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    return lines


def _has_merge_tree(repo_root: str) -> bool:
    """Check if git merge-tree --write-tree is available (Git 2.38+)."""
    result = subprocess.run(
        ["git", "-C", repo_root, "merge-tree", "--write-tree", "main", "main"],
        capture_output=True, timeout=10,
    )
    return result.returncode == 0


def _list_sun_branches(repo_root: str) -> List[str]:
    """List all local YOK-* branches."""
    result = subprocess.run(
        ["git", "-C", repo_root, "branch", "--list", "YOK-*"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        return []
    branches = []
    for line in result.stdout.splitlines():
        branch = line.lstrip("* ").strip()
        if branch:
            branches.append(branch)
    return branches


def _check_conflict(repo_root: str, left_branch: str, right_branch: str) -> List[str]:
    """Trial merge via git merge-tree, return list of conflicting files."""
    result = subprocess.run(
        [
            "git", "-C", repo_root, "merge-tree", "--write-tree",
            left_branch, right_branch,
        ],
        capture_output=True, text=True, timeout=30,
    )
    conflict_files = []
    for line in result.stdout.splitlines():
        if "CONFLICT" in line:
            # Extract file path from conflict line
            m = re.sub(r".*CONFLICT \([^)]*\): ", "", line)
            fname = m.split()[0] if m else ""
            if fname:
                conflict_files.append(fname)
    return sorted(set(conflict_files))


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

from yoke_core.engines.merge_audit_report import generate_report  # noqa: E402,F401

def main() -> None:
    """CLI: ``python3 -m yoke_core.engines.merge_audit [epic-id]``."""
    epic_filter: Optional[int] = None
    if len(sys.argv) > 1:
        raw = re.sub(r"^[Yy][Oo][Kk]-", "", sys.argv[1])
        try:
            epic_filter = int(raw)
        except ValueError:
            print(f"Error: invalid epic ID: {sys.argv[1]}", file=sys.stderr)
            sys.exit(1)

    print(generate_report(epic_filter), end="")

if __name__ == "__main__":
    main()
