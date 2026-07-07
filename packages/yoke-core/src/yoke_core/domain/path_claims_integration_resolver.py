"""Deliberate integration-target resolution for path claims.

Wraps the low-level primitive
:func:`yoke_core.domain.path_claims_boundary_git.resolve_integration_head`
with one piece of doctrine the bare lookup does not encode:

**Origin-then-local with divergence check.** The canonical SHA for an
integration target is the tip of ``refs/remotes/origin/<target>`` when
it exists, otherwise the tip of ``refs/heads/<target>``. When both
exist and have *diverged* (neither is an ancestor of the other), the
resolver raises :class:`IntegrationTargetDiverged` *before* activate or
boundary check tries anything — operators see one clear "reconcile
push/pull" message rather than a downstream surface mismatch.

The boundary module also reaches for :func:`compute_anchor_sha` to
anchor its diff range. The anchor is the **dynamic merge-base** of the
resolved integration head and the worktree HEAD — i.e. the actual DAG
fork point of the branch under check. ``path_claims.base_commit_sha``
remains as an activation-time audit artifact (it records "what was the
integration target's tip when activation ran?") but is **not**
load-bearing for boundary diff range computation. Anchoring on the
fork point is self-healing for both directions of routine drift:
``origin/main`` moving forward after activation does not pollute the
diff (the LCA is unchanged), and a branch built from a local ``main``
that was already ahead of ``origin/main`` at activation no longer
inherits unrelated commits as false positives.

The existing primitive in :mod:`path_claims_boundary_git` stays as-is —
this module imports rather than mutates it, and reuses
:func:`path_claims_boundary_git.merge_base` for fork-point computation
rather than authoring a duplicate ``git merge-base`` helper.
"""

from __future__ import annotations

import subprocess
from typing import Any, Optional

from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError,
    merge_base as _merge_base,
    resolve_integration_head as _resolve_origin_then_local,
)


class IntegrationTargetDiverged(BoundaryCheckError):
    """Raised when ``origin/<target>`` and ``refs/heads/<target>`` have diverged.

    Surfaces before activate or boundary check tries anything so the
    operator sees one coherent "reconcile (push/pull/rebase) before
    activating" message rather than a downstream snapshot mismatch.
    """


def _ref_sha(repo_path: str, ref: str) -> Optional[str]:
    proc = subprocess.run(
        ["git", "-C", repo_path, "rev-parse", "--verify", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _is_ancestor(repo_path: str, ancestor: str, descendant: str) -> bool:
    proc = subprocess.run(
        ["git", "-C", repo_path, "merge-base", "--is-ancestor",
         ancestor, descendant],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def _check_divergence(
    repo_path: str,
    integration_target: str,
) -> None:
    """Raise :class:`IntegrationTargetDiverged` when origin and local diverged.

    Both refs must exist for divergence to be possible. If only one ref
    exists, there is nothing to diverge from.
    """
    origin_sha = _ref_sha(
        repo_path, f"refs/remotes/origin/{integration_target}"
    )
    local_sha = _ref_sha(repo_path, f"refs/heads/{integration_target}")
    if origin_sha is None or local_sha is None:
        return
    if origin_sha == local_sha:
        return
    if _is_ancestor(repo_path, origin_sha, local_sha):
        return  # local ahead of origin — fine
    if _is_ancestor(repo_path, local_sha, origin_sha):
        return  # origin ahead of local — fine
    raise IntegrationTargetDiverged(
        f"origin/{integration_target} and refs/heads/{integration_target} "
        f"have diverged in {repo_path}. Reconcile (push, pull, or rebase) "
        f"before activating."
    )


def resolve_integration_head_with_divergence_check(
    conn: Any,
    *,
    project_id: str,
    repo_path: str,
    integration_target: str,
) -> str:
    """Resolve the integration head commit SHA.

    Returns the resolved ``commit_sha``. The canonical resolution rule:
    tip of ``refs/remotes/origin/<integration_target>`` if it exists,
    otherwise tip of ``refs/heads/<integration_target>``.

    Raises :class:`IntegrationTargetDiverged` when origin and local
    have diverged (neither ancestor of the other) — caller is expected
    to surface the reconcile guidance and stop.
    Raises :class:`BoundaryCheckError` when neither ref exists.

    ``conn`` and ``project_id`` are retained on the signature for
    callers that still pass them; the resolver itself no longer touches
    either since the snapshot-mint hot path was removed.
    """
    del conn, project_id  # retained for caller compatibility, unused
    _check_divergence(repo_path, integration_target)
    return _resolve_origin_then_local(repo_path, integration_target)


def _newer_ancestor_sha(
    repo_path: str, integration_target: str
) -> str:
    """Return whichever of ``origin/<target>`` or ``refs/heads/<target>``
    is the newer ancestor — the appropriate side to merge-base with the
    branch under check.

    When ``origin`` and ``local`` both exist and one is an ancestor of
    the other, the descendant is the more accurate "where main is right
    now" reference for the boundary diff: it captures unpushed commits
    on local main that the operator's branch was forked from. When only
    one ref exists, that ref is used. Divergence is enforced upstream
    by calling the same divergence checker used during activation, so
    a post-activation push/pull mismatch blocks the boundary gate
    before a misleading diff can be computed.
    """
    _check_divergence(repo_path, integration_target)
    origin_sha = _ref_sha(
        repo_path, f"refs/remotes/origin/{integration_target}"
    )
    local_sha = _ref_sha(repo_path, f"refs/heads/{integration_target}")
    if origin_sha and local_sha:
        if origin_sha == local_sha:
            return origin_sha
        if _is_ancestor(repo_path, origin_sha, local_sha):
            return local_sha
        if _is_ancestor(repo_path, local_sha, origin_sha):
            return origin_sha
        raise IntegrationTargetDiverged(
            f"origin/{integration_target} and "
            f"refs/heads/{integration_target} have diverged in {repo_path}. "
            "Reconcile (push, pull, or rebase) before activating."
        )
    if origin_sha:
        return origin_sha
    if local_sha:
        return local_sha
    raise BoundaryCheckError(
        f"cannot resolve integration target {integration_target!r} in "
        f"{repo_path}; tried refs/remotes/origin and refs/heads"
    )


def compute_anchor_sha(
    *,
    repo_path: str,
    integration_target: str,
    head_sha: str,
) -> str:
    """Return the diff-range anchor for boundary checks.

    The anchor is the dynamic merge-base of the resolved integration
    head and ``head_sha`` — the actual DAG fork point of the branch
    under check. The integration head is the descendant of
    ``origin/<target>`` and ``refs/heads/<target>`` when both exist,
    so unpushed commits on local main do not become false positives
    for branches that were forked off local. ``path_claims.base_commit_sha``
    is preserved as an activation-time audit artifact but is not
    consulted here; routine forward and backward drift on the
    integration target leaves the fork point unchanged, so the diff
    range stays correct without operator intervention.

    Raises :class:`BoundaryCheckError` when the integration target
    cannot be resolved or when ``git merge-base`` fails.
    """
    integration_sha = _newer_ancestor_sha(repo_path, integration_target)
    return _merge_base(repo_path, integration_sha, head_sha)


def diff_window(
    repo_path: str,
    integration_target: str,
    worktree_head: Optional[str],
):
    """Return committed-diff ``(touched_paths, rename_pairs)`` for the
    range anchored on ``merge-base(integration_head, head_sha)``.

    Extracted from :mod:`path_claims_boundary` to keep that module
    under its line budget. Boundary callers route through this helper
    so the merge-base anchor stays the single source of truth.
    """
    from yoke_core.domain.path_claims_boundary_git import (
        collect_committed_changes,
        resolve_worktree_head,
    )
    head_sha = (
        worktree_head or resolve_worktree_head(repo_path)
    ).strip()
    base_sha = compute_anchor_sha(
        repo_path=repo_path,
        integration_target=integration_target,
        head_sha=head_sha,
    )
    return collect_committed_changes(
        repo_path, base_sha=base_sha, head_sha=head_sha
    )


__all__ = [
    "IntegrationTargetDiverged",
    "compute_anchor_sha",
    "diff_window",
    "resolve_integration_head_with_divergence_check",
]
