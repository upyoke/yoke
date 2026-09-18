"""Applying one claim-coverage repair's widen and narrow.

The mechanical half of
:mod:`idea_readiness_repair_claim_coverage`: given paths that repair
already decided on, resolve them to claim targets, amend the claim, and
emit the amendment event. Deciding *which* paths, and whether the repair
may run at all, stays with the caller.

Every failure is returned as a refusal rather than raised, because a
repair reports what it could not do alongside what it did — and a narrow
that would orphan committed work is the case that matters most, since
refusing it is the correct outcome rather than an error.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.idea_readiness_repair import RepairedPath
from yoke_core.domain.idea_readiness_repair_handoff import (
    narrow_refusal_without_checkout,
)
from yoke_core.domain.path_claims import PathClaimError
from yoke_core.domain.path_claims_amend import (
    AmendmentError,
    NarrowWouldOrphanCommittedWork,
    narrow,
    widen,
)
from yoke_core.domain.path_claims_events import emit_amended
from yoke_core.domain.path_claims_read import claim_projection
from yoke_core.domain.path_claims_resolve import (
    PathResolveError,
    resolve_paths_to_target_ids,
)

WIDEN_REASON = "refine entry: auto-widen for FILE_BUDGET_NOT_IN_CLAIM"
NARROW_REASON = "refine entry: auto-narrow for CLAIM_NOT_IN_FILE_BUDGET"

_AMEND_EXCS = (AmendmentError, PathClaimError, PathResolveError)


def _repaired(paths: List[str]) -> List[RepairedPath]:
    """Claim coverage repairs membership, so the count fields carry no reading."""
    return [RepairedPath(path=p, recorded=0, actual=0) for p in paths]


def apply_widen(
    conn, *, claim_id: int, project: str, paths: List[str],
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    """Add every File Budget path the claim was missing."""
    try:
        target_ids = resolve_paths_to_target_ids(conn, project, paths)
        amendment_id = widen(
            conn, claim_id=claim_id, add_target_ids=target_ids,
            reason=WIDEN_REASON,
        )
        emit_amended(
            conn=conn, claim=claim_projection(conn, claim_id),
            amendment_id=amendment_id, amendment_kind="widen",
            payload={"added": list(target_ids)},
            reason=WIDEN_REASON, project=project,
        )
    except _AMEND_EXCS as exc:
        return [], [{"reason": "widen_failed", "paths": list(paths),
                     "error": str(exc)}]
    return _repaired(paths), []


def apply_narrow(
    conn, *, claim_id: int, project: str, drop_paths: List[str],
    repo_path: Optional[str],
) -> Tuple[List[RepairedPath], List[Dict[str, Any]]]:
    """Drop every claimed path the File Budget no longer lists."""
    refusal = narrow_refusal_without_checkout(repo_path, drop_paths)
    if refusal is not None:
        return [], [refusal]
    try:
        target_ids = resolve_paths_to_target_ids(conn, project, drop_paths)
        amendment_id = narrow(
            conn, claim_id=claim_id, drop_target_ids=target_ids,
            reason=NARROW_REASON, repo_path=repo_path,
        )
        emit_amended(
            conn=conn, claim=claim_projection(conn, claim_id),
            amendment_id=amendment_id, amendment_kind="narrow",
            payload={"removed": list(target_ids)},
            reason=NARROW_REASON, project=project,
        )
    except NarrowWouldOrphanCommittedWork as exc:
        return [], [{
            "reason": "narrow_boundary_risk",
            "offending_paths": list(exc.offending_paths),
            "error": str(exc),
        }]
    except _AMEND_EXCS as exc:
        return [], [{"reason": "narrow_failed",
                     "drop_paths": list(drop_paths), "error": str(exc)}]
    return _repaired(drop_paths), []


__all__ = [
    "NARROW_REASON",
    "WIDEN_REASON",
    "apply_narrow",
    "apply_widen",
]
