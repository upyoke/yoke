"""Fail-closed sweep of merged, terminal, unclaimed lanes on this machine.

The per-lane retirement at landing (``merge_landed_lane_cleanup``) can refuse
— a dirty tree, a locked worktree, an incomplete remote delete — and nothing
retries it on its own. This sweep is that retry: every landing boundary on a
machine runs it after its own lane is handled, so a lane one landing
preserved is examined again by the next. It never widens the rules: the
control plane must name a terminal owner with no live authority
(``merge.prune.authority_verdict`` over the active transport), the tree must
be clean once disposable caches are gone, the branch must be contained in
``origin/<target>``, and the remote branch goes before any local ref.
Unreachable authority skips everything. What was removed and what was kept,
each with its reason, comes back as a :class:`WorktreeSweep` so the landing
that ran the sweep can show it instead of burying it in progress output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.engines.merge_worktree_cleanliness import (
    clean_after_disposable_cache_removal,
)


@dataclass(frozen=True)
class _Worktree:
    path: Path
    branch: str
    # Git's lock note; ``None`` when the worktree is not locked.
    lock_reason: str | None = None


@dataclass(frozen=True)
class PreservedLane:
    path: str
    reason: str


@dataclass(frozen=True)
class WorktreeSweep:
    """What one sweep removed and what it left on disk, each with a reason."""

    removed: tuple[str, ...] = ()
    preserved: tuple[PreservedLane, ...] = ()
    skipped: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "removed": list(self.removed),
            "preserved": [asdict(lane) for lane in self.preserved],
            "skipped": self.skipped,
        }


def _runtime_git() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _run_git

    return _run_git


def _runtime_emit() -> Callable[..., Any]:
    from yoke_core.engines._merge_worktree_runtime import _print

    return _print


def first_output_line(result: Any) -> str:
    """The first meaningful line git wrote, or its exit code."""
    detail = (result.stderr or result.stdout or "").strip()
    return detail.splitlines()[0] if detail else f"exit {result.returncode}"


def registered_worktrees(
    run_git: Callable[..., Any], repo_root: str
) -> list[_Worktree] | None:
    """Every branch-bearing worktree git registers, or ``None`` when it cannot say."""
    result = run_git(["worktree", "list", "--porcelain"], cwd=repo_root, capture=True)
    if result.returncode != 0:
        return None
    entries: list[_Worktree] = []
    block: dict[str, str] = {}
    for line in [*result.stdout.splitlines(), ""]:
        if not line:
            if "branch" in block:
                entries.append(
                    _Worktree(
                        Path(block["worktree"]).resolve(),
                        block["branch"],
                        block.get("locked"),
                    )
                )
            block = {}
        elif line.startswith("worktree "):
            block["worktree"] = line.removeprefix("worktree ")
        elif line.startswith("branch refs/heads/"):
            block["branch"] = line.removeprefix("branch refs/heads/")
        elif line == "locked" or line.startswith("locked "):
            block["locked"] = line.removeprefix("locked").strip()
    return entries


def is_managed_worktree_path(path: Path, repo_root: Path) -> bool:
    """Whether ``path`` sits under a root Yoke creates lanes in."""
    roots = (repo_root / ".worktrees", repo_root / ".claude" / "worktrees")
    return any(path != root and path.is_relative_to(root) for root in roots)


def _merged(
    run_git: Callable[..., Any],
    repo_root: str,
    branch: str,
    base: str,
) -> bool:
    result = run_git(
        ["merge-base", "--is-ancestor", branch, base],
        cwd=repo_root,
        capture=True,
    )
    return result.returncode == 0


def _prune_verdict(
    branch: str, path: Path | None, state: dict[str, bool]
) -> dict[str, Any] | None:
    """Relay the fail-closed authority verdict for one branch / worktree.

    Returns the verdict dict, or ``None`` when DB authority is unreachable
    over the active transport (flagged on *state* so the caller skips all
    pruning). The terminal owner + active authority reads run server-side;
    the prune/keep decision and every git deletion stay client-side.
    """
    try:
        resp = call_dispatcher(
            function_id="merge.prune.authority_verdict",
            target=TargetRef(kind="global"),
            payload={"branch": branch, "path": (str(path) if path else None)},
        )
    except Exception:  # noqa: BLE001 - transport failure == authority unavailable
        state["unavailable"] = True
        return None
    if not resp.success:
        state["unavailable"] = True
        return None
    return resp.result or {}


def _delete_remote_before_local(
    *,
    run_git: Callable[..., Any],
    emit: Callable[..., Any],
    repo_root: str,
    branch: str,
    target: str,
) -> Any:
    """Prove and delete ``origin/<branch>`` before discarding local refs."""
    from yoke_core.engines.remote_branch_cleanup import delete_remote_branch_if_merged

    result = delete_remote_branch_if_merged(
        run_git=lambda command: run_git(command, cwd=repo_root, capture=True),
        branch=branch,
        target_branch=target,
    )
    if result.status == "deleted":
        emit(f"Deleted merged remote branch: origin/{branch}")
    elif result.status == "preserved":
        emit(f"Preserving remote branch origin/{branch}: {result.reason}")
    return result


def _skipped(
    emit: Callable[..., Any],
    reason: str,
    removed: tuple[str, ...] = (),
    preserved: tuple[PreservedLane, ...] = (),
) -> WorktreeSweep:
    emit(f"Skipping automatic worktree pruning: {reason}")
    return WorktreeSweep(removed, preserved, reason)


def prune_managed_worktrees(
    *,
    repo_root: str,
    target: str,
    run_git: Callable[..., Any] | None = None,
    emit: Callable[..., Any] | None = None,
) -> WorktreeSweep:
    """Prune clean, unclaimed, terminal lanes after remote-first delete.

    Authority verdicts relay via ``merge.prune.authority_verdict``; git stays
    local. Unreachable DB authority skips pruning. Incomplete remote cleanup
    preserves the local retry lane. Every kept lane is named with its reason
    on the returned sweep as well as on ``emit``.
    """
    git = run_git or _runtime_git()
    say = emit or _runtime_emit()
    root = Path(repo_root).resolve()
    base = f"origin/{target}"
    fetched = git(["fetch", "origin", target], cwd=repo_root, capture=True)
    if fetched.returncode != 0:
        return _skipped(say, f"could not refresh {base}")
    entries = registered_worktrees(git, repo_root)
    if entries is None:
        return _skipped(say, "worktree registry unavailable")

    removed: list[str] = []
    preserved: list[PreservedLane] = []

    def keep(path: Path, reason: str) -> None:
        say(f"Preserving worktree {path}: {reason}")
        preserved.append(PreservedLane(str(path), reason))

    state = {"unavailable": False}
    checked_out = {entry.branch for entry in entries}
    for entry in entries:
        if not is_managed_worktree_path(entry.path, root):
            continue
        verdict = _prune_verdict(entry.branch, entry.path, state)
        if state["unavailable"]:
            return _skipped(
                say, "DB authority unavailable", tuple(removed), tuple(preserved)
            )
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            if verdict.get("reason") == "active_authority":
                keep(entry.path, "actively claimed")
            continue
        if entry.lock_reason is not None:
            keep(
                entry.path,
                f"worktree is locked ({entry.lock_reason or 'no reason recorded'})",
            )
            continue
        if not clean_after_disposable_cache_removal(git, entry.path):
            keep(entry.path, "dirty or unverifiable worktree")
            continue
        if not _merged(git, repo_root, entry.branch, base):
            keep(entry.path, f"unmerged worktree branch {entry.branch}")
            continue
        remote = _delete_remote_before_local(
            run_git=git,
            emit=say,
            repo_root=repo_root,
            branch=entry.branch,
            target=target,
        )
        if not remote.cleanup_complete:
            keep(entry.path, f"remote cleanup incomplete: {remote.reason}")
            continue
        removal = git(
            ["worktree", "remove", str(entry.path)],
            cwd=repo_root,
            capture=True,
        )
        if removal.returncode != 0:
            keep(entry.path, f"removal refused: {first_output_line(removal)}")
            continue
        say(f"Pruned terminal merged worktree: {entry.path}")
        removed.append(str(entry.path))
        checked_out.discard(entry.branch)
        deleted = git(["branch", "-d", entry.branch], cwd=repo_root, capture=True)
        if deleted.returncode != 0:
            say(f"Preserved local branch after delete refusal: {entry.branch}")

    branches = git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads"],
        cwd=repo_root,
        capture=True,
    )
    if branches.returncode != 0:
        return WorktreeSweep(tuple(removed), tuple(preserved))
    for branch in branches.stdout.splitlines():
        if branch in checked_out or branch == target:
            continue
        verdict = _prune_verdict(branch, None, state)
        if state["unavailable"]:
            return _skipped(
                say, "DB authority unavailable", tuple(removed), tuple(preserved)
            )
        assert verdict is not None  # not unavailable -> a dict
        if not verdict.get("prunable"):
            continue
        if not _merged(git, repo_root, branch, base):
            continue
        if not _delete_remote_before_local(
            run_git=git,
            emit=say,
            repo_root=repo_root,
            branch=branch,
            target=target,
        ).cleanup_complete:
            continue
        deleted = git(["branch", "-d", branch], cwd=repo_root, capture=True)
        if deleted.returncode == 0:
            say(f"Pruned terminal merged local branch: {branch}")
    return WorktreeSweep(tuple(removed), tuple(preserved))


__all__ = [
    "PreservedLane",
    "WorktreeSweep",
    "first_output_line",
    "is_managed_worktree_path",
    "prune_managed_worktrees",
    "registered_worktrees",
]
