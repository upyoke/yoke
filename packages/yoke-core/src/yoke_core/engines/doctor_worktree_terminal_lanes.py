"""Terminal lanes the worktree-health check assesses and reports.

Each terminal lane's prune proof needs a control-plane authority verdict.
Reading them per lane cost a round trip each, so a machine holding dozens of
landed lanes spent the whole check budget on reads. Here every verdict
arrives in one batched read, and ancestry, remote and checkout identity come
from one shared git inventory. The check only reports: the standing relay's
periodic lane sweep is what removes a lane proved finished.

Lanes that stay on disk are named by why, operator-first, for the check's
one-line summary.
"""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List

from yoke_core.engines.doctor_worktree_lane_authority import (
    ACTIVE_AUTHORITY_BLOCK,
    LaneKey,
    authority_blocks,
)
from yoke_core.engines.lane_cleanup_reads import LaneCleanupReads
from yoke_core.engines.merge_landed_lane_cleanup import (
    LaneCleanupAssessment,
    assess_landed_lane,
)

DEPLOY_RUN_CATEGORY = "finished deploy run"
# Summary order: what needs an operator first, what the relay sweep removes last.
STRANDED_ORDER = (
    "dirty",
    DEPLOY_RUN_CATEGORY,
    "locked",
    "unregistered directory",
    "claimed",
    "unmerged",
    "preserved",
    "sweep-ready",
)


class TerminalLaneAssessor:
    """Assess terminal lanes against batched authority verdicts."""

    def __init__(
        self,
        lanes: Iterable[LaneKey],
        *,
        git_for_repo: Callable[[str], Callable[..., object]],
        residues: Dict[str, object] | None = None,
        checkouts: Iterable[dict] | None = None,
    ) -> None:
        self._authority = authority_blocks(lanes)
        self._git_for_repo = git_for_repo
        self._residues = residues or {}
        self._worktrees: Dict[str, str] = {}
        for entry in checkouts or ():
            branch = str(entry.get("branch") or "")
            path = str(entry.get("path") or "")
            if branch and path and branch not in self._worktrees:
                self._worktrees[branch] = path
        self._reads_by_root: Dict[str, LaneCleanupReads] = {}

    @property
    def authority_failure(self) -> str:
        """Why the batched verdict read could not answer; empty when it did."""
        return self._authority.failure

    def assess(
        self, *, root: str, branch: str, path: str, target: str
    ) -> LaneCleanupAssessment:
        """Prove one lane against the target as this checkout last fetched it."""
        return assess_landed_lane(
            repo_root=root,
            branch=branch,
            target=target,
            run_git=self._git_for_repo(root),
            refresh_target=False,
            authority_block=self._authority.block(branch, path),
            reads=self._reads(root),
        )

    def _reads(self, root: str) -> LaneCleanupReads:
        reads = self._reads_by_root.get(root)
        if reads is None:
            reads = LaneCleanupReads(
                self._git_for_repo(root),
                root,
                residues=self._residues,
                worktrees=self._worktrees,
            )
            self._reads_by_root[root] = reads
        return reads


def stranded_category(entry: dict, residue, assessment) -> tuple[str, str]:
    """Name why a terminal item's lane is still on disk, operator-first."""
    if "locked" in entry:
        return "locked", entry["locked"]
    if residue is not None and not residue.removable_once_landed:
        count = len(residue.precious_paths)
        if not count:
            return "preserved", residue.reason
        return "dirty", f"{count} modified file{'s' if count != 1 else ''}"
    if assessment.safe:
        return "sweep-ready", ""
    reason = assessment.reason
    if ACTIVE_AUTHORITY_BLOCK in reason:
        return "claimed", reason.split("preserved: ", 1)[-1]
    if "not merged" in reason:
        return "unmerged", reason.split("preserved: ", 1)[-1]
    return "preserved", reason.split("preserved: ", 1)[-1]


def stranded_summary(stranded: Dict[str, List[str]]) -> str:
    total = sum(len(refs) for refs in stranded.values())
    parts = [
        f"{category} ({', '.join(stranded[category])})"
        for category in STRANDED_ORDER
        if stranded.get(category)
    ]
    plural = "s" if total != 1 else ""
    return f"- {total} released lane{plural} still on disk: " + ", ".join(parts)


__all__ = [
    "DEPLOY_RUN_CATEGORY",
    "STRANDED_ORDER",
    "TerminalLaneAssessor",
    "stranded_category",
    "stranded_summary",
]
