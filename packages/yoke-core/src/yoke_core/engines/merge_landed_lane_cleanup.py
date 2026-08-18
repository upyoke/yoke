"""Retiring one item lane whose branch has landed on the target branch.

A lane is four things describing one piece of work — a worktree directory, a
local branch, a remote branch, and the control-plane row that records where
they live — so they retire together. Leaving any one behind strands the next
reader that resolves a lane by its recorded path, and leaving all of them
behind is what an operator eventually sweeps by hand.

Two merge boundaries reach this. Queue-less standalone merges defer cleanup
until the pushed commit's checks conclude, while queue landings merge on
GitHub and have no inline cleanup step. Both prune the whole lane here. A
remote-backed lane proves the landing against a freshly fetched
``origin/<target>``; a local-only repository proves it against its local
target branch.

Every step fails toward preserving. An unmerged branch, a dirty worktree, an
ambiguous remote, or a refused deletion leaves the lane in place with the
reason named, because a preserved lane costs an operator one sweep while a
wrongly deleted one costs the work.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.engines.merge_worktree_safe_prune import (
    is_managed_worktree_path,
    registered_worktrees,
)
from yoke_core.engines.remote_branch_cleanup import (
    delete_remote_branch_if_merged,
)


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _runtime_emit() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _print

    return _print


@dataclass(frozen=True)
class LaneCleanupAssessment:
    """Read-only proof for whether one landed lane may be retired."""

    safe: bool
    reason: str = ""
    worktree_path: Optional[Path] = None
    base: str = ""
    has_remote: bool = False


@dataclass(frozen=True)
class WorktreeResidueAssessment:
    """Whether Git reports only repository-declared ignored residue."""

    safe: bool
    ignored_only: bool = False
    reason: str = ""


def assess_worktree_residue(
    run_git: Callable[..., Any], worktree_path: str | Path
) -> WorktreeResidueAssessment:
    """Classify tracked, unignored, and ignored worktree content through Git."""
    root = Path(worktree_path).resolve()
    current = run_git(
        [
            "-C",
            str(root),
            "status",
            "--porcelain=v1",
            "--ignored=matching",
            "--untracked-files=all",
        ],
        cwd=str(root),
        capture=True,
    )
    if current.returncode != 0:
        return WorktreeResidueAssessment(False, reason="status unreadable")

    ignored_paths: list[str] = []
    precious_paths: list[str] = []
    for line in (current.stdout or "").splitlines():
        path = line[3:] if len(line) > 3 else line
        if line.startswith("!! "):
            ignored_paths.append(path)
        else:
            precious_paths.append(path)
    if precious_paths:
        return WorktreeResidueAssessment(
            False,
            reason="unignored changes present: " + ", ".join(precious_paths),
        )
    return WorktreeResidueAssessment(True, ignored_only=bool(ignored_paths))


_TERMINAL_OWNED_RELEASE = ("acquire one first", "claim_required")


def _row_release_warning(branch: str, detail: str) -> Optional[str]:
    """Name a stranded row; stay silent when the terminal transition owns it."""
    text = detail.lower()
    if any(marker in text for marker in _TERMINAL_OWNED_RELEASE):
        return None
    return (
        f"WARNING: lane row for {branch} left active after "
        f"worktree removal: {detail}"
    )


def release_lane_row(
    item_id: Optional[int | str],
    branch: str,
    *,
    emit: Callable[..., Any],
) -> Optional[str]:
    """Retire the lane row after its directory is gone. Advisory on failure.

    A claim_required refusal is not a stranded row: the terminal status
    transaction already released the lane. Other failures still warn, and
    the warning is returned so the merge envelope can carry it.
    """
    if not item_id:
        return None
    try:
        from yoke_core.api.service_client_structured_api_adapter import (
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="item_worktrees.release_merged_lane",
            target=TargetRef(kind="item", item_id=int(item_id)),
            payload={"branch": branch},
        )
    except Exception as exc:  # noqa: BLE001 - advisory, never unwinds a merge
        detail = str(exc)
    else:
        if response.success:
            return None
        detail = (
            response.error.message
            if response.error is not None
            else "release refused"
        )
    warning = _row_release_warning(branch, detail)
    if warning:
        emit(warning, err=True)
    return warning


def _lane_worktree(
    run_git: Callable[..., Any], repo_root: str, branch: str
) -> Optional[Path]:
    """The managed worktree directory checked out on ``branch``, if any."""
    entries = registered_worktrees(run_git, repo_root)
    if entries is None:
        return None
    root = Path(repo_root).resolve()
    for entry in entries:
        if entry.branch == branch and is_managed_worktree_path(entry.path, root):
            return entry.path
    return None


def _remove_empty_parent(path: Path) -> None:
    parent = path.parent
    if "/.worktrees" not in str(parent):
        return
    try:
        if not list(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def assess_landed_lane(
    *,
    repo_root: str,
    branch: str,
    target: str,
    run_git: Optional[Callable[..., Any]] = None,
    refresh_target: bool = True,
    authority_block: str = "",
) -> LaneCleanupAssessment:
    """Prove claim authority, cleanliness, and target ancestry without deletion."""
    git = run_git or _runtime_git()
    remotes = git(["remote"], cwd=repo_root, capture=True)
    has_remote = remotes.returncode == 0 and bool(remotes.stdout.strip())
    base = f"origin/{target}" if has_remote else target
    worktree_path = _lane_worktree(git, repo_root, branch)
    lane_name = f"lane {branch}"
    if worktree_path is not None:
        lane_name += f" at {worktree_path}"
    if authority_block:
        return LaneCleanupAssessment(
            False,
            f"{lane_name} preserved: {authority_block}",
            worktree_path,
            base,
            has_remote,
        )
    if has_remote and refresh_target:
        fetched = git(["fetch", "origin", target], cwd=repo_root, capture=True)
        if fetched.returncode != 0:
            return LaneCleanupAssessment(
                False,
                f"lane {branch} preserved: could not refresh {base}",
                worktree_path,
                base,
                has_remote,
            )
    landed = git(
        ["merge-base", "--is-ancestor", branch, base],
        cwd=repo_root,
        capture=True,
    )
    if landed.returncode != 0:
        return LaneCleanupAssessment(
            False,
            f"lane {branch} preserved: branch is not merged into {base}",
            worktree_path,
            base,
            has_remote,
        )
    if worktree_path is not None:
        residue = assess_worktree_residue(git, worktree_path)
        if not residue.safe:
            return LaneCleanupAssessment(
                False,
                f"{lane_name} preserved: worktree is dirty or unverifiable "
                f"({residue.reason})",
                worktree_path,
                base,
                has_remote,
            )
    return LaneCleanupAssessment(
        True,
        worktree_path=worktree_path,
        base=base,
        has_remote=has_remote,
    )


def prune_landed_lane(
    *,
    repo_root: str,
    branch: str,
    target: str,
    item_id: Optional[int | str] = None,
    run_git: Optional[Callable[..., Any]] = None,
    emit: Optional[Callable[..., Any]] = None,
    authority_block: str = "",
) -> tuple[str, ...]:
    """Retire one landed lane; return the reasons anything was preserved.

    An empty result means the lane is gone: no remote branch, no worktree, no
    local branch, and a released row. Any other result names what survived and
    why, so the caller can surface it instead of reporting a clean landing over
    a lane that is still on disk.
    """
    git = run_git or _runtime_git()
    say = emit or _runtime_emit()
    assessment = assess_landed_lane(
        repo_root=repo_root,
        branch=branch,
        target=target,
        run_git=git,
        authority_block=authority_block,
    )
    if not assessment.safe:
        return (assessment.reason,)

    if assessment.has_remote:
        remote = delete_remote_branch_if_merged(
            run_git=lambda command: git(command, cwd=repo_root, capture=True),
            branch=branch,
            target_branch=target,
        )
        if remote.status == "deleted":
            say(f"Deleted merged remote branch: origin/{branch}")
        if not remote.cleanup_complete:
            return (
                f"lane {branch} preserved so remote cleanup can be retried: "
                f"{remote.reason}",
            )

    worktree_path = assessment.worktree_path
    if worktree_path is not None:
        residue = assess_worktree_residue(git, worktree_path)
        if not residue.safe:
            return (
                f"lane {branch} preserved: worktree {worktree_path} is dirty "
                f"or unverifiable ({residue.reason})",
            )
        remove_args = ["worktree", "remove"]
        if residue.ignored_only:
            remove_args.append("--force")
        remove_args.append(str(worktree_path))
        removed = git(
            remove_args,
            cwd=repo_root,
            capture=True,
        )
        if removed.returncode != 0:
            return (
                f"lane {branch} preserved: worktree removal refused for "
                f"{worktree_path}",
            )
        say(f"Pruned merged worktree: {worktree_path}")
        _remove_empty_parent(worktree_path)

    row_warning = release_lane_row(item_id, branch, emit=say)
    notes = (row_warning,) if row_warning else ()

    deleted = git(["branch", "-D", branch], cwd=repo_root, capture=True)
    if deleted.returncode != 0:
        return notes + (f"local branch {branch} preserved after delete refusal",)
    say(f"Pruned merged local branch: {branch}")
    return notes


__all__ = [
    "LaneCleanupAssessment",
    "WorktreeResidueAssessment",
    "assess_landed_lane",
    "assess_worktree_residue",
    "prune_landed_lane",
    "release_lane_row",
]
