"""Repository facts a lane sweep reads once and reuses for every lane.

Remote presence, which branches the target already contains, and which
managed checkout holds a branch are properties of the repository, not of
one lane. Asking git for each of them once per lane spent the worktree-health
check's budget on a machine holding a full set of lanes, before any removal
could start. Callers that already classified a checkout pass that residue in
so the sweep does not status the same directory again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from yoke_core.engines.branch_landed_evidence import (
    ANCESTOR_PROOF,
    BranchLandedEvidence,
    detached_head,
)
from yoke_core.engines.git_worktree_registry import is_managed_worktree_path


class LaneCleanupReads:
    """One git inventory shared across every lane proved in a sweep."""

    def __init__(
        self,
        run_git: Callable[..., Any],
        repo_root: str,
        *,
        residues: Dict[str, Any],
        worktrees: Dict[str, str],
    ) -> None:
        self._git = run_git
        self._root = repo_root
        self._residues = residues
        self._worktrees = worktrees
        self._has_remote: Optional[bool] = None
        self._merged: Dict[str, Optional[set[str]]] = {}
        self._main: Optional[Path] = None

    def has_remote(self) -> bool:
        if self._has_remote is None:
            result = self._git(["remote"], cwd=self._root, capture=True)
            self._has_remote = result.returncode == 0 and bool(
                (result.stdout or "").strip()
            )
        return self._has_remote

    def worktree_for(self, branch: str) -> Optional[Path]:
        """The managed checkout of ``branch``, or none when it is not checked out.

        The sweep may be running inside one lane. Sibling lanes live under the
        common checkout's ``.worktrees``, not under that lane.
        """
        raw = self._worktrees.get(branch)
        if not raw:
            return None
        path = Path(raw)
        if not is_managed_worktree_path(path.resolve(), self._common_root()):
            return None
        return path

    def _common_root(self) -> Path:
        if self._main is None:
            result = self._git(
                ["rev-parse", "--git-common-dir"], cwd=self._root, capture=True
            )
            common = Path((result.stdout or "").strip() or ".git")
            if not common.is_absolute():
                common = Path(self._root) / common
            self._main = (
                common.resolve().parent
                if common.name == ".git"
                else Path(self._root).resolve()
            )
        return self._main

    def ancestor(self, branch: str, base: str) -> Optional[BranchLandedEvidence]:
        """Ancestry from one ``--merged`` read.

        ``None`` means this branch still needs the per-branch proof: a detached
        commit, an unreadable ref list, or a branch the target does not contain.
        Not contained is not "unlanded" — a rebased branch can still be
        patch-equivalent, and that proof stays with the caller.
        """
        if detached_head(branch):
            return None
        merged = self._merged_into(base)
        if merged is None or branch not in merged:
            return None
        return BranchLandedEvidence(True, proof=ANCESTOR_PROOF)

    def residue(self, path: Path) -> Any:
        """A residue classification the caller already computed, if any."""
        found = self._residues.get(str(path))
        if found is None:
            found = self._residues.get(str(path.resolve()))
        return found

    def _merged_into(self, base: str) -> Optional[set[str]]:
        if base not in self._merged:
            result = self._git(
                [
                    "for-each-ref",
                    "--format=%(refname:short)",
                    "--merged",
                    base,
                    "refs/heads",
                ],
                cwd=self._root,
                capture=True,
            )
            if result.returncode != 0:
                self._merged[base] = None
            else:
                self._merged[base] = {
                    line for line in (result.stdout or "").splitlines() if line
                }
        return self._merged[base]


__all__ = ["LaneCleanupReads"]
