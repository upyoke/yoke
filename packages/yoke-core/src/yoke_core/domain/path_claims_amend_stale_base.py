"""Stale-base-on-new-claim validation for path-claim widen.

Sibling of :mod:`path_claims_amend` that owns the second of widen's
two distinct safety questions:

  1. Does the new coverage overlap another non-terminal claim on the
     same ``integration_target``? (Owned by :mod:`path_claims_overlap`.)
  2. Did the current ``integration_target`` change a newly requested
     path *after* this claim's base point, and has the working branch
     reconciled that change? (This module.)

The diagnostic name is :class:`StaleBaseOnNewClaim` and the error code
string is ``stale-base-on-new-claim``. It is intentionally distinct
from ``claim_overlap`` / :class:`IncompatibleOverlap` so callers can
branch on diagnostic kind: a stale-base failure is not a live
occupancy collision and must not be routed first to
``PathClaimOverride``.

Comparison anchor: the recorded ``path_claims.base_commit_sha`` (the
integration-target HEAD at activation time). Compare that commit
against the current integration-target HEAD via
:mod:`path_claims_boundary_git`.

Reconciliation check: the working branch ``HEAD`` includes the
current integration-target HEAD as an ancestor (``git merge-base
--is-ancestor``). If true, the working branch has merged or rebased
the change in and the widen may proceed. If false and the new path
changed, the widen is rejected.
"""

from __future__ import annotations

import subprocess
from typing import Any, List, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import PathClaimError
from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError,
    resolve_integration_head,
    run_git,
)
from yoke_core.domain.path_claims_boundary_targets import (
    path_string_map_for_target_ids,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class StaleBaseOnNewClaim(PathClaimError):
    """Widen rejected because main changed a new path after the claim's base.

    The exception payload carries the specific paths and target ids so
    callers can surface remediation guidance verbatim.
    """

    error_code = "stale-base-on-new-claim"

    def __init__(
        self,
        claim_id: int,
        offending_paths: Sequence[str],
        offending_target_ids: Sequence[int],
        base_commit_sha: str,
        integration_target_head_sha: str,
        integration_target: str,
    ) -> None:
        self.claim_id = claim_id
        self.offending_paths = list(offending_paths)
        self.offending_target_ids = list(offending_target_ids)
        self.base_commit_sha = base_commit_sha
        self.integration_target_head_sha = integration_target_head_sha
        self.integration_target = integration_target
        super().__init__(
            f"stale-base-on-new-claim for claim {claim_id}: "
            f"{integration_target!r} changed these paths between the "
            f"claim's base ({base_commit_sha[:8]}) and current HEAD "
            f"({integration_target_head_sha[:8]}): "
            f"{', '.join(self.offending_paths)}. "
            "Reconcile the working branch with the current "
            f"{integration_target} (rebase or merge), inspect the "
            "landed change, then retry the widen if the path is still "
            "needed."
        )


def _changed_paths_between(
    repo_path: str, base_sha: str, head_sha: str,
) -> set[str]:
    """Return the set of paths the integration_target touched in the range.

    Uses ``git diff --name-only`` so only mutated paths surface; renames
    show up under their old or new name depending on git's choice — for
    stale-base purposes either side counts as "changed".
    """
    if base_sha == head_sha:
        return set()
    raw = run_git(
        repo_path, "diff", "--name-only", "-z",
        f"{base_sha}..{head_sha}",
    )
    if not raw:
        return set()
    parts = [p for p in raw.split("\x00") if p]
    return set(parts)


def _branch_includes_head(
    repo_path: str, integration_head: str, worktree_head: str,
) -> bool:
    """True iff ``worktree_head`` includes ``integration_head`` as ancestor."""
    proc = subprocess.run(
        [
            "git", "-C", repo_path, "merge-base", "--is-ancestor",
            integration_head, worktree_head,
        ],
        capture_output=True, text=True, check=False,
    )
    return proc.returncode == 0


def check_stale_base_on_new_claim(
    conn: Any,
    *,
    claim_id: int,
    new_target_ids: Sequence[int],
    repo_path: str,
    worktree_head: Optional[str] = None,
) -> None:
    """Raise :class:`StaleBaseOnNewClaim` if any new path is stale-base.

    Returns ``None`` when:

    * the claim has no recorded ``base_commit_sha`` (never activated),
    * the integration target's HEAD matches the recorded commit
      (no drift),
    * none of the new paths changed in the integration target since
      the recorded commit, or
    * the working branch has already reconciled the integration head.
    """
    if not new_target_ids:
        return None

    p = _p(conn)
    claim_row = conn.execute(
        "SELECT base_commit_sha, integration_target FROM path_claims "
        f"WHERE id = {p}",
        (claim_id,),
    ).fetchone()
    if claim_row is None:
        return None
    base_commit_sha = claim_row[0]
    integration_target = str(claim_row[1])
    if not base_commit_sha:
        return None
    base_commit_sha = str(base_commit_sha)

    try:
        integration_head = resolve_integration_head(
            repo_path, integration_target,
        )
    except BoundaryCheckError:
        return None

    if integration_head == base_commit_sha:
        return None

    try:
        changed = _changed_paths_between(
            repo_path, base_commit_sha, integration_head,
        )
    except BoundaryCheckError:
        return None
    if not changed:
        return None

    new_path_map = path_string_map_for_target_ids(conn, new_target_ids)
    new_pairs = [
        (int(target_id), new_path_map[int(target_id)])
        for target_id in new_target_ids
        if int(target_id) in new_path_map
    ]
    offending: List[tuple[int, str]] = [
        (tid, path) for (tid, path) in new_pairs if path in changed
    ]
    if not offending:
        return None

    if worktree_head and _branch_includes_head(
        repo_path, integration_head, worktree_head,
    ):
        return None

    raise StaleBaseOnNewClaim(
        claim_id=claim_id,
        offending_paths=[p for _, p in offending],
        offending_target_ids=[t for t, _ in offending],
        base_commit_sha=base_commit_sha,
        integration_target_head_sha=integration_head,
        integration_target=integration_target,
    )


__all__ = [
    "StaleBaseOnNewClaim",
    "check_stale_base_on_new_claim",
]
