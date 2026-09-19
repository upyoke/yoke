"""What a deployment-run Browser case is required to be looking at.

A case attached to a deployment run exists to certify what that run
delivered, so the commit it is judged against comes from the run itself.
Before this, the expectation arrived as ``--expected-branch`` /
``--expected-sha`` command-line arguments, which the deployment stage never
supplies: every production-certifying capture was therefore recorded with no
code identity at all and ``freshness_validated`` false, while the same case
run by hand was bound properly. The run has always known which commit it
froze; nothing asked it.
"""

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

    Returns ``(failure, branch, sha)``. A caller-supplied commit is allowed
    only when it agrees with the run's own: the run is authority over what it
    shipped, so a disagreement is a contradiction to report rather than a
    choice to make.
    """
    source = context.get("run_source") or {}
    pinned = str(source.get("sha") or "").strip()
    if not pinned:
        return (
            FreshnessFailure(
                DEPLOYMENT_SOURCE_UNPINNED,
                f"Deployment run {deployment_run_id} names no commit it was "
                "pinned to deliver, so there is nothing for this case's "
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
                f"was pinned to deliver {pinned}, but {supplied} was named for "
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
