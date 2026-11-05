"""Retain an unpublished merge and retry over release pin commits."""

from yoke_core.domain import standalone_item_merge_git as git
from yoke_core.domain.deployment_run_release_output import RELEASE_PIN_SUBJECT_PREFIX

PIN_REFRESH_ATTEMPTS = 2


def _run(repo_root: str, *args: str) -> str:
    result = git._git(repo_root, *args)
    if result.returncode:
        raise RuntimeError(
            f"merge_pin_refresh_failed: {result.stderr or result.stdout}. "
            "Keep the retained branches; refresh the lane and rerun the merge"
        )
    return result.stdout.strip()


def pin_only_advance(repo_root: str, target: str) -> bool:
    fetched = git._git(repo_root, "fetch", "origin", target)
    if fetched.returncode:
        return False
    result = git._git(repo_root, "log", "--format=%s", f"{target}..origin/{target}")
    subjects = result.stdout.splitlines()
    return (
        result.returncode == 0
        and bool(subjects)
        and all(subject.startswith(RELEASE_PIN_SUBJECT_PREFIX) for subject in subjects)
    )


def reset_target_to_origin(repo_root: str, branch: str, target: str) -> str:
    head = _run(repo_root, "rev-parse", f"refs/heads/{target}")
    retained = f"{branch}-unpublished-{head[:12]}"
    if not git.branch_exists(repo_root, retained):
        _run(repo_root, "branch", retained, head)
    elif git.head_of(repo_root, retained) != head:
        raise RuntimeError(
            f"merge_pin_retention_conflict: {retained} holds a different commit. "
            "Preserve it and refresh the lane manually"
        )
    # The target may be checked out in the primary checkout or another lane.
    listing = _run(repo_root, "worktree", "list", "--porcelain")
    for record in listing.split("\n\n"):
        lines = record.splitlines()
        if f"branch refs/heads/{target}" in lines:
            checkout = next(
                line.removeprefix("worktree ")
                for line in lines
                if line.startswith("worktree ")
            )
            _run(checkout, "reset", "--keep", f"origin/{target}")
            return retained
    _run(repo_root, "branch", "-f", target, f"origin/{target}")
    return retained
