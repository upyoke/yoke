"""Git-side helpers for the path-claim boundary check.

Splits out of :mod:`yoke_core.domain.path_claims_boundary` to keep
that module within its line budget. Owns the three concrete git
operations the boundary check needs:

* resolving the integration target to a SHA, trying
  ``refs/remotes/origin/<target>`` then ``refs/heads/<target>``,
* resolving the worktree HEAD to a SHA, and
* collecting the rename-aware ``git diff --name-status`` output between
    the merge-base and the worktree HEAD, and
* detecting unresolved staged / unstaged / untracked worktree drift so
  boundary callers can block advancement before transient edits are
  mistaken for a clean committed boundary.

Errors surface as :class:`BoundaryCheckError` so the caller's existing
try/except contract still catches them; the boundary module re-exports
the class so consumers import from one module.
"""

from __future__ import annotations

import subprocess
from typing import List, Sequence, Tuple


class BoundaryCheckError(Exception):
    """Raised for unrecoverable git I/O failures."""


def run_git(repo_path: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", repo_path, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise BoundaryCheckError(
            f"git {' '.join(args)} failed in {repo_path}: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    return proc.stdout


def resolve_integration_head(
    repo_path: str, integration_target: str
) -> str:
    """Resolve the integration target ref to a SHA, trying origin then local heads."""
    for ref in (
        f"refs/remotes/origin/{integration_target}",
        f"refs/heads/{integration_target}",
    ):
        proc = subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", ref],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if sha:
                return sha
    raise BoundaryCheckError(
        f"cannot resolve integration target {integration_target!r} in "
        f"{repo_path}; tried refs/remotes/origin and refs/heads"
    )


def resolve_worktree_head(repo_path: str) -> str:
    sha = run_git(repo_path, "rev-parse", "HEAD").strip()
    if not sha:
        raise BoundaryCheckError(
            f"git rev-parse HEAD produced empty SHA in {repo_path}"
        )
    return sha


def collect_committed_changes(
    repo_path: str,
    *,
    base_sha: str,
    head_sha: str,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return ``(touched_paths, rename_pairs)`` for the diff range.

    ``touched_paths`` carries the affected new path for additions,
    modifications, deletions, and the destination of renames; entries
    are deduplicated while preserving operator-visible order.
    ``rename_pairs`` captures ``(old_path, new_path)`` tuples for every
    detected rename.
    """
    raw = run_git(
        repo_path,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        f"{base_sha}..{head_sha}",
    )
    parts = raw.split("\x00")
    touched: List[str] = []
    renames: List[Tuple[str, str]] = []
    i = 0
    while i < len(parts):
        token = parts[i]
        if not token:
            i += 1
            continue
        op = token[0]
        if op == "R":
            old_path = parts[i + 1] if i + 1 < len(parts) else ""
            new_path = parts[i + 2] if i + 2 < len(parts) else ""
            if new_path:
                touched.append(new_path)
            if old_path and new_path:
                renames.append((old_path, new_path))
            i += 3
        elif op in ("A", "M", "D", "T"):
            path = parts[i + 1] if i + 1 < len(parts) else ""
            if path:
                touched.append(path)
            i += 2
        else:
            i += 1
    seen: set[str] = set()
    deduped: List[str] = []
    for path in touched:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped, renames


def collect_worktree_drift(repo_path: str) -> List[str]:
    """Return staged / unstaged / untracked paths that are not committed."""
    raw = run_git(
        repo_path,
        "status",
        "--porcelain",
        "--untracked-files=all",
    )
    out: List[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def merge_base(
    repo_path: str, target_head_sha: str, head_sha: str
) -> str:
    base = run_git(repo_path, "merge-base", target_head_sha, head_sha).strip()
    if not base:
        raise BoundaryCheckError(
            f"git merge-base produced empty SHA for {target_head_sha} .. "
            f"{head_sha} in {repo_path}"
        )
    return base


def filter_gitignored_paths(
    repo_path: str, paths: Sequence[str]
) -> Tuple[List[str], List[str]]:
    """Split ``paths`` into ``(kept, ignored)`` per the repo's ignore rules.

    Uses ``git check-ignore --no-index --stdin`` so paths already tracked
    by git are still classified against ``.gitignore``. Without
    ``--no-index`` git suppresses output for tracked paths, which is the
    opposite of what the boundary check needs: an ignored-but-force-added
    file is exactly the case we want to skip when classifying committed
    work against declared coverage.
    """
    if not paths:
        return [], []
    proc = subprocess.run(
        ["git", "-C", repo_path, "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise BoundaryCheckError(
            f"git check-ignore failed in {repo_path}: "
            f"{(proc.stderr or proc.stdout).strip()}"
        )
    ignored = {line for line in proc.stdout.splitlines() if line}
    kept = [path for path in paths if path not in ignored]
    ignored_ordered = [path for path in paths if path in ignored]
    return kept, ignored_ordered


__all__ = [
    "BoundaryCheckError",
    "collect_committed_changes",
    "collect_worktree_drift",
    "filter_gitignored_paths",
    "merge_base",
    "resolve_integration_head",
    "resolve_worktree_head",
    "run_git",
]
