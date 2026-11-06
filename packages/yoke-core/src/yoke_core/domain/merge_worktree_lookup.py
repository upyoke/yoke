"""Find a registered Git worktree for a branch."""

from yoke_core.domain import standalone_item_merge_git as git


def _find_worktree(branch: str, repo_root: str) -> str:
    """Find the worktree path for a branch, or fall back to repo root."""
    result = git._git(repo_root, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        return repo_root

    current_wt = ""
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            current_wt = line[len("worktree ") :]
        elif line == f"branch refs/heads/{branch}":
            return current_wt

    return repo_root
