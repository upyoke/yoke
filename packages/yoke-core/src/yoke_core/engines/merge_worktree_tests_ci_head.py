"""Verified head-sha binding for the merge boundary's post-rebase CI run."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.engines import merge_worktree_tree_coverage


def _parent():
    from yoke_core.engines import merge_worktree as _mw

    return _mw


def covered_head_sha(
    *,
    project: str,
    repo: str,
    ci_run_id: str,
    candidate_sha: str,
    worktree: Path,
) -> str:
    """The commit the CI run tested, proven to carry the candidate tree.

    The run is read back through the relay rather than trusting the branch
    we pushed, because between push and dispatch the ref can move. When the
    control plane answers without a head sha — an engine older than that
    field — the check degrades by name to the commit we published, which is
    the binding the dispatch itself carried.
    """
    mw = _parent()
    ci_head = qa_case_ci_lane.run_head_sha(
        project=project, repo=repo, run_id=ci_run_id,
    )
    if not ci_head:
        mw._print(
            "[phase:tests] control plane reports no head sha for CI run "
            f"{ci_run_id}; binding the verdict to the published candidate "
            f"{candidate_sha[:12]} instead of the run's reported head"
        )
        return candidate_sha
    candidate_tree = merge_worktree_tree_coverage._tree_object_id(worktree, "HEAD")
    ci_tree = merge_worktree_tree_coverage._tree_object_id(worktree, ci_head)
    if candidate_tree is None or ci_tree is None or candidate_tree != ci_tree:
        raise QaCaseExecutionError(
            f"CI head sha {ci_head} does not resolve to the candidate "
            f"tree (candidate={candidate_tree}, ci={ci_tree})"
        )
    return ci_head


__all__ = ["covered_head_sha"]
