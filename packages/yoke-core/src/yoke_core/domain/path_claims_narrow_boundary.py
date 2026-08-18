"""Boundary validation for local and relayed path-claim narrowing."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckError,
    BoundaryCheckResult,
    BoundaryCheckStatus,
    boundary_check_for_paths,
    classify_against_coverage,
)
from yoke_core.domain.schema_common import _table_exists


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _active_lane_head(
    conn: Any,
    *,
    item_id: int,
    repo_root: Optional[str] = None,
) -> Optional[str]:
    if not _table_exists(conn, "item_worktrees"):
        return None
    marker = _p(conn)
    path_filter = f" AND path = {marker}" if repo_root else ""
    params: tuple[Any, ...] = (item_id, repo_root) if repo_root else (item_id,)
    row = conn.execute(
        "SELECT commit_sha FROM item_worktrees "
        f"WHERE item_id = {marker} AND state = 'active'{path_filter} "
        "ORDER BY id DESC LIMIT 1",
        params,
    ).fetchone()
    if row is None:
        return None
    value = row[0] if not hasattr(row, "keys") else row["commit_sha"]
    return str(value) if value else ""


def _evidence_boundary(
    conn: Any,
    *,
    claim: dict,
    project_id: int,
    candidate_paths: Sequence[str],
    evidence: Mapping[str, Any],
) -> BoundaryCheckResult:
    claim_id = int(claim["id"])
    integration_target = str(claim["integration_target"])
    evidence_target = str(evidence.get("integration_target") or "")
    if evidence_target != integration_target:
        raise BoundaryCheckError(
            "boundary evidence integration target does not match claim "
            f"{claim_id}: {evidence_target!r} <> {integration_target!r}"
        )
    repo_root = str(evidence.get("repo_root") or "")
    head_sha = str(evidence.get("head_sha") or "")
    if not repo_root or not head_sha:
        raise BoundaryCheckError(
            "boundary evidence requires repo_root and a committed head_sha"
        )
    owner_item_id = claim.get("owner_item_id")
    if owner_item_id is None:
        raise BoundaryCheckError(
            f"claim {claim_id} has no item owner for lane-head verification"
        )
    recorded_head = _active_lane_head(
        conn,
        item_id=int(owner_item_id),
        repo_root=repo_root,
    )
    if not recorded_head:
        if (
            not claim.get("activated_at")
            and not claim.get("base_commit_sha")
            and _active_lane_head(conn, item_id=int(owner_item_id)) is None
        ):
            return _never_activated_boundary(
                conn, claim=claim, candidate_paths=candidate_paths
            )
        raise BoundaryCheckError(
            "no synced active lane head matches the boundary evidence; run "
            f"`yoke project snapshot sync {repo_root}` and retry"
        )
    if recorded_head != head_sha:
        raise BoundaryCheckError(
            "boundary evidence head does not match the synced active lane: "
            f"{head_sha[:12]} <> {recorded_head[:12]}"
        )

    touched_paths = list(dict.fromkeys(evidence.get("touched_paths") or []))
    uncommitted_paths = list(dict.fromkeys(evidence.get("uncommitted_paths") or []))
    rename_pairs = [
        (str(pair[0]), str(pair[1])) for pair in evidence.get("rename_pairs") or []
    ]
    if uncommitted_paths:
        return BoundaryCheckResult(
            status=BoundaryCheckStatus.CONFLICT,
            claim_id=claim_id,
            integration_target=integration_target,
            declared_paths=list(candidate_paths),
            uncommitted_paths=uncommitted_paths,
            declared_but_untouched_paths=list(candidate_paths),
            diagnostics=(
                "candidate coverage cannot be checked while the worktree "
                "has staged, unstaged, or untracked changes"
            ),
        )
    (
        undeclared_paths,
        undeclared_target_ids,
        declared_but_untouched_paths,
        _has_rename_resolved,
    ) = classify_against_coverage(
        conn,
        project_id=project_id,
        declared_paths=candidate_paths,
        touched_paths=touched_paths,
        rename_pairs=rename_pairs,
    )
    return BoundaryCheckResult(
        status=(
            BoundaryCheckStatus.CONFLICT
            if undeclared_paths
            else BoundaryCheckStatus.VALID
        ),
        claim_id=claim_id,
        integration_target=integration_target,
        declared_paths=list(candidate_paths),
        touched_paths=touched_paths,
        undeclared_paths=undeclared_paths,
        undeclared_target_ids=undeclared_target_ids,
        declared_but_untouched_paths=declared_but_untouched_paths,
        rename_pairs=rename_pairs,
        diagnostics=(
            "narrowed coverage would leave committed work outside the claim"
            if undeclared_paths
            else "candidate coverage contains every committed touch"
        ),
    )


def _never_activated_boundary(
    conn: Any,
    *,
    claim: dict,
    candidate_paths: Sequence[str],
) -> BoundaryCheckResult:
    claim_id = int(claim["id"])
    owner_item_id = claim.get("owner_item_id")
    active_head = (
        _active_lane_head(conn, item_id=int(owner_item_id))
        if owner_item_id is not None
        else None
    )
    if (
        claim.get("activated_at")
        or claim.get("base_commit_sha")
        or active_head is not None
    ):
        raise BoundaryCheckError(
            "narrowing an activated or checked-out claim requires synced "
            "boundary evidence from its active lane"
        )
    return BoundaryCheckResult(
        status=BoundaryCheckStatus.VALID,
        claim_id=claim_id,
        integration_target=str(claim["integration_target"]),
        declared_paths=list(candidate_paths),
        diagnostics="never-activated claim has no committed lane work to orphan",
    )


def check_narrow_boundary(
    conn: Any,
    *,
    claim: dict,
    project_id: int,
    candidate_paths: Sequence[str],
    repo_path: Optional[str] = None,
    worktree_head: Optional[str] = None,
    boundary_evidence: Optional[Mapping[str, Any]] = None,
) -> BoundaryCheckResult:
    """Validate candidate coverage using local git or relayed lane evidence."""
    if repo_path:
        return boundary_check_for_paths(
            conn,
            project_id=project_id,
            candidate_paths=candidate_paths,
            integration_target=str(claim["integration_target"]),
            repo_path=repo_path,
            worktree_head=worktree_head,
        )
    if boundary_evidence is not None:
        return _evidence_boundary(
            conn,
            claim=claim,
            project_id=project_id,
            candidate_paths=candidate_paths,
            evidence=boundary_evidence,
        )
    return _never_activated_boundary(
        conn,
        claim=claim,
        candidate_paths=candidate_paths,
    )


__all__ = ["check_narrow_boundary"]
