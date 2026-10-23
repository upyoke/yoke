"""Resolve release identity for fresh QA and observed identity for inherited QA."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from yoke_core.domain.browser_qa_freshness_outcome import (
    DEPLOYMENT_SOURCE_CONTRADICTED,
    DEPLOYMENT_SOURCE_UNPINNED,
    FreshnessFailure,
)


def run_bound_identity(
    deployment_run_id: str,
    context: Mapping[str, Any],
    *,
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> Tuple[Optional[FreshnessFailure], str, str]:
    """Resolve the branch and commit a run-bound case must be judged against.

    Inherited QA records the environment's observed commit instead of imposing
    the current release's commit. Returns ``(failure, branch, sha)``.
    For fresh QA, a caller-supplied commit is allowed
    only when it agrees with the run's own: the run is authority over what it
    shipped, so a disagreement is a contradiction to report rather than a
    choice to make.
    """
    source = context.get("run_source") or {}
    if source.get("identity_scope") == "environment":
        return None, str(source.get("branch") or ""), ""
    pinned = str(source.get("sha") or "").strip()
    project = str(source.get("project") or "").strip()
    whose = f" for project {project!r}" if project else ""
    if not pinned:
        return (
            FreshnessFailure(
                DEPLOYMENT_SOURCE_UNPINNED,
                f"Deployment run {deployment_run_id} names no commit it "
                f"delivered{whose}, so there is nothing for this case's "
                "evidence to be bound to and no way to tell whether the "
                "environment is serving what the run shipped. Bind the run to "
                "its release lineage before running its QA.",
            ),
            "",
            "",
        )
    supplied = str(expected_sha or "").strip()
    if supplied and supplied != pinned:
        return (
            FreshnessFailure(
                DEPLOYMENT_SOURCE_CONTRADICTED,
                f"This case verifies deployment run {deployment_run_id}, which "
                f"delivered {pinned}{whose}, but {supplied} was named for "
                "it. A run is authority over what it shipped. Drop the "
                "expected-commit argument and let the run supply it, or run "
                "the case against the run that delivered that commit.",
            ),
            "",
            "",
        )
    branch = str(expected_branch or source.get("branch") or "").strip()
    return None, branch, pinned


__all__ = ["run_bound_identity"]
