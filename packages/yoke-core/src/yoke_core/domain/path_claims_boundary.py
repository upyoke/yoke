"""Committed-git boundary check for path claims.

Compares declared coverage with committed work since the dynamic
merge-base for the claim's integration target. Dirty worktrees return
``conflict`` before coverage matching. The activation commit SHA is an
audit artifact; the dynamic fork point is what defines the diff range.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import get_claim
from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError, collect_worktree_drift, filter_gitignored_paths,
)
from yoke_core.domain.path_claims_boundary_targets import path_strings_for_target_ids
from yoke_core.domain.path_registry import target_at


def _p(conn: Any) -> str: return "%s" if db_backend.connection_is_postgres(conn) else "?"


class BoundaryCheckStatus(enum.Enum):
    VALID = "valid"
    DRIFTED = "drifted"
    RENAME_RESOLVED = "rename_resolved"
    CONFLICT = "conflict"


@dataclass
class BoundaryCheckResult:
    status: BoundaryCheckStatus
    claim_id: int
    integration_target: str
    declared_target_ids: List[int] = field(default_factory=list)
    declared_paths: List[str] = field(default_factory=list)
    touched_paths: List[str] = field(default_factory=list)
    uncommitted_paths: List[str] = field(default_factory=list)
    undeclared_paths: List[str] = field(default_factory=list)
    undeclared_target_ids: List[int] = field(default_factory=list)
    declared_but_untouched_paths: List[str] = field(default_factory=list)
    rename_pairs: List[Tuple[str, str]] = field(default_factory=list)
    diagnostics: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "claim_id": self.claim_id,
            "integration_target": self.integration_target,
            "declared_target_ids": list(self.declared_target_ids),
            "declared_paths": list(self.declared_paths),
            "touched_paths": list(self.touched_paths),
            "uncommitted_paths": list(self.uncommitted_paths),
            "undeclared_paths": list(self.undeclared_paths),
            "undeclared_target_ids": list(self.undeclared_target_ids),
            "declared_but_untouched_paths": list(
                self.declared_but_untouched_paths
            ),
            "rename_pairs": [list(pair) for pair in self.rename_pairs],
            "diagnostics": self.diagnostics,
        }


def _project_for_claim(
    conn: Any, claim: dict
) -> Optional[int]:
    item_id = claim.get("item_id")
    if item_id is None:
        return None
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    project_id = row[0] if not hasattr(row, "keys") else row["project_id"]
    return int(project_id) if project_id else None


def _classify_against_coverage(
    conn: Any,
    *,
    project_id: Optional[int],
    declared_paths: Sequence[str],
    touched_paths: Sequence[str],
    rename_pairs: Sequence[Tuple[str, str]],
) -> Tuple[List[str], List[int], List[str], bool]:
    declared_set = set(declared_paths)
    undeclared_paths: List[str] = []
    undeclared_target_ids: List[int] = []
    for path in touched_paths:
        if path in declared_set:
            continue
        undeclared_paths.append(path)
        if project_id:
            target_id = target_at(conn, project_id, path)
            if target_id is not None:
                undeclared_target_ids.append(int(target_id))
    declared_but_untouched_paths = [
        path for path in declared_paths if path not in touched_paths
    ]
    has_rename_resolved = any(
        old in declared_set and new in declared_set
        for (old, new) in rename_pairs
    )
    return (
        undeclared_paths,
        undeclared_target_ids,
        declared_but_untouched_paths,
        has_rename_resolved,
    )


def _target_ids_for_paths(
    conn: Any,
    *,
    project_id: Optional[int],
    paths: Sequence[str],
) -> List[int]:
    if not project_id:
        return []
    return [
        int(target_id)
        for path in paths
        if (target_id := target_at(conn, project_id, path)) is not None
    ]


def _decide_status(
    *,
    undeclared_paths: Sequence[str],
    declared_but_untouched_paths: Sequence[str],
    touched_paths: Sequence[str],
    has_rename_resolved: bool,
    rename_pairs: Sequence[Tuple[str, str]],
) -> Tuple[BoundaryCheckStatus, str]:
    if undeclared_paths:
        return (
            BoundaryCheckStatus.CONFLICT,
            f"{len(undeclared_paths)} committed file(s) outside declared "
            "coverage; remediate via amend (widen), revert, or split",
        )
    if has_rename_resolved:
        return (
            BoundaryCheckStatus.RENAME_RESOLVED,
            f"{len(rename_pairs)} rename(s) detected; declared coverage "
            "spans both endpoints",
        )
    if declared_but_untouched_paths and not touched_paths:
        return (
            BoundaryCheckStatus.DRIFTED,
            "no committed work touches declared coverage; the claim may be "
            "stale (release or wait)",
        )
    if declared_but_untouched_paths:
        return (
            BoundaryCheckStatus.DRIFTED,
            f"{len(declared_but_untouched_paths)} declared path(s) untouched; "
            "narrow the claim or proceed if intentional",
        )
    return (
        BoundaryCheckStatus.VALID,
        "every committed change resolves to declared coverage",
    )


def _diff_window(*args, **kwargs):
    """Boundary diff window — delegates to the resolver module's helper."""
    from yoke_core.domain.path_claims_integration_resolver import diff_window
    return diff_window(*args, **kwargs)


def boundary_check_for_claim(
    conn: Any,
    *,
    claim_id: int,
    repo_path: str,
    worktree_head: Optional[str] = None,
) -> BoundaryCheckResult:
    """Compare the worktree's committed diff against a claim's declared coverage."""
    claim = get_claim(conn, claim_id)
    integration_target = str(claim["integration_target"])
    project_id = _project_for_claim(conn, claim)
    declared_target_ids = [int(tid) for tid in claim.get("target_ids") or []]
    declared_paths = path_strings_for_target_ids(conn, declared_target_ids)
    dirty_paths = collect_worktree_drift(repo_path)
    if dirty_paths:
        return BoundaryCheckResult(
            status=BoundaryCheckStatus.CONFLICT,
            claim_id=claim_id,
            integration_target=integration_target,
            declared_target_ids=declared_target_ids,
            declared_paths=declared_paths,
            uncommitted_paths=dirty_paths,
            undeclared_target_ids=_target_ids_for_paths(
                conn, project_id=project_id, paths=dirty_paths,
            ),
            declared_but_untouched_paths=list(declared_paths),
            diagnostics=(
                "working tree has staged, unstaged, or untracked changes; "
                "commit, revert, or stash them before the boundary advances"
            ),
        )
    touched_paths, rename_pairs = _diff_window(
        repo_path, integration_target, worktree_head,
    )
    touched_paths, _ = filter_gitignored_paths(repo_path, touched_paths)
    (
        undeclared_paths,
        undeclared_target_ids,
        declared_but_untouched_paths,
        has_rename_resolved,
    ) = _classify_against_coverage(
        conn,
        project_id=project_id,
        declared_paths=declared_paths,
        touched_paths=touched_paths,
        rename_pairs=rename_pairs,
    )
    status, diagnostics = _decide_status(
        undeclared_paths=undeclared_paths,
        declared_but_untouched_paths=declared_but_untouched_paths,
        touched_paths=touched_paths,
        has_rename_resolved=has_rename_resolved,
        rename_pairs=rename_pairs,
    )
    return BoundaryCheckResult(
        status=status,
        claim_id=claim_id,
        integration_target=integration_target,
        declared_target_ids=declared_target_ids,
        declared_paths=declared_paths,
        touched_paths=touched_paths,
        undeclared_paths=undeclared_paths,
        undeclared_target_ids=undeclared_target_ids,
        declared_but_untouched_paths=declared_but_untouched_paths,
        rename_pairs=rename_pairs,
        diagnostics=diagnostics,
    )


def boundary_check_for_paths(
    conn: Any,
    *,
    project_id: int,
    candidate_paths: Sequence[str],
    integration_target: str,
    repo_path: str,
    worktree_head: Optional[str] = None,
) -> BoundaryCheckResult:
    """Hypothetical boundary check for amend (narrow) re-checks.

    Used by :mod:`yoke_core.domain.path_claims_amend` to ask "would
    this set of paths still cover every committed change?" without
    persisting the narrow first. The result mirrors the real check
    shape so amend can format the same rejection diagnostics.
    """
    touched_paths, rename_pairs = _diff_window(
        repo_path, integration_target, worktree_head
    )
    touched_paths, _ = filter_gitignored_paths(repo_path, touched_paths)
    dirty_paths = collect_worktree_drift(repo_path)
    if dirty_paths:
        return BoundaryCheckResult(
            status=BoundaryCheckStatus.CONFLICT,
            claim_id=-1,
            integration_target=integration_target,
            declared_paths=list(candidate_paths),
            uncommitted_paths=dirty_paths,
            undeclared_target_ids=_target_ids_for_paths(
                conn, project_id=project_id, paths=dirty_paths,
            ),
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
    ) = _classify_against_coverage(
        conn,
        project_id=project_id,
        declared_paths=list(candidate_paths),
        touched_paths=touched_paths,
        rename_pairs=rename_pairs,
    )
    if undeclared_paths:
        status = BoundaryCheckStatus.CONFLICT
        diagnostics = (
            "narrowed coverage would leave committed work outside the claim"
        )
    elif declared_but_untouched_paths and not touched_paths:
        status = BoundaryCheckStatus.DRIFTED
        diagnostics = "candidate coverage has no committed touches yet"
    elif declared_but_untouched_paths:
        status = BoundaryCheckStatus.DRIFTED
        diagnostics = "candidate coverage is wider than committed touches"
    else:
        status = BoundaryCheckStatus.VALID
        diagnostics = "candidate coverage matches committed touches exactly"
    return BoundaryCheckResult(
        status=status,
        claim_id=-1,
        integration_target=integration_target,
        declared_target_ids=[],
        declared_paths=list(candidate_paths),
        touched_paths=touched_paths,
        undeclared_paths=undeclared_paths,
        undeclared_target_ids=undeclared_target_ids,
        declared_but_untouched_paths=declared_but_untouched_paths,
        rename_pairs=rename_pairs,
        diagnostics=diagnostics,
    )


__all__ = [
    "BoundaryCheckError",
    "BoundaryCheckResult",
    "BoundaryCheckStatus",
    "boundary_check_for_claim",
    "boundary_check_for_paths",
]
