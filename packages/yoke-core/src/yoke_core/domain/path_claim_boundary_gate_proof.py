"""Caller-produced path-boundary proof for checkout-less control planes.

The local CLI observes git state where the item's lane actually lives. The
server records that observation only after binding it to current authoritative
item facts, then revalidates those facts when a hosted lifecycle gate consumes
the proof. Direct local gates continue to inspect the checkout themselves.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Sequence

from yoke_core.domain.gate_satisfier_ladder import LadderResolution
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    PATH_CLAIM_BOUNDARY_LADDER,
)
from yoke_core.domain.gate_satisfier_stamp import read_rungs, record_rung
from yoke_core.domain.path_claims_boundary import (
    BoundaryCheckStatus,
    boundary_check_for_paths,
)
from yoke_core.domain.path_claims_boundary_git import (
    LOCAL_INTEGRATION_REF,
    REMOTE_INTEGRATION_REF,
    resolve_ref,
    resolve_worktree_head,
)
from yoke_core.domain.path_claims_integration_resolver import compute_anchor_sha
from yoke_core.domain.path_claim_boundary_proof_validation import (
    BoundaryProofError,
    PROOF_FACT,
    PROOF_KIND,
    validate_proof,
)


def _canonical_claim(claim: Dict[str, Any]) -> dict:
    target_ids = claim.get("target_ids") or [
        target.get("target_id") for target in claim.get("declared_targets") or []
    ]
    paths = claim.get("declared_paths") or [
        target.get("path_string") for target in claim.get("declared_targets") or []
    ]
    return {
        "claim_id": int(claim["id"]),
        "state": str(claim.get("state") or ""),
        "integration_target": str(claim.get("integration_target") or ""),
        "declared_target_ids": sorted(int(value) for value in target_ids),
        "declared_paths": sorted(str(value) for value in paths),
    }


def boundary_context(conn: Any, item_id: int) -> dict:
    """Return the authoritative facts a caller must bind into its proof."""
    try:
        return _load_boundary_context(conn, item_id)
    except BoundaryProofError:
        raise
    except Exception as exc:
        raise BoundaryProofError(
            f"authoritative boundary context is unreadable: {type(exc).__name__}: {exc}"
        ) from exc


def _load_boundary_context(conn: Any, item_id: int) -> dict:
    from yoke_core.domain.item_worktrees import primary_item_worktree
    from yoke_core.domain.path_claims_gate_boundary import claims_for_boundary
    from yoke_core.domain.path_claims_read import claim_projection
    from yoke_core.domain.sessions_queries_lookup import get_claim_for_work_unit

    row = conn.execute(
        "SELECT p.id, p.slug FROM items i JOIN projects p ON p.id=i.project_id "
        "WHERE i.id = %s",
        (item_id,),
    ).fetchone()
    if row is None:
        raise BoundaryProofError(f"item {item_id} was not found")
    claims = [
        _canonical_claim(claim_projection(conn, claim_id))
        for claim_id, _target in claims_for_boundary(conn, item_id)
    ]
    lane = primary_item_worktree(conn, item_id)
    holder = get_claim_for_work_unit(conn, item_id=str(item_id))
    return {
        "item_id": item_id,
        "project": {"id": int(row[0]), "slug": str(row[1])},
        "lane": _canonical_lane(lane),
        "work_claim": _canonical_work_claim(holder),
        "claims": claims,
    }


def _canonical_lane(lane: Any) -> dict | None:
    if not lane:
        return None
    return {
        "id": int(lane["id"]),
        "item_id": int(lane["item_id"]),
        "branch": str(lane.get("branch") or ""),
        "path": str(lane.get("path") or ""),
        "commit_sha": str(lane.get("commit_sha") or ""),
        "lane_role": str(lane.get("lane_role") or ""),
        "state": str(lane.get("state") or ""),
    }


def _canonical_work_claim(holder: Any) -> dict | None:
    if not holder:
        return None
    return {
        "claim_id": int(holder["id"]),
        "session_id": str(holder.get("session_id") or ""),
    }


def build_local_boundary_proof(context: dict, repo_path: str) -> dict:
    """Inspect the recorded lane with the existing boundary checker."""
    try:
        return _build_local_boundary_proof(context, repo_path)
    except BoundaryProofError:
        raise
    except Exception as exc:
        raise BoundaryProofError(
            f"local boundary check could not run: {type(exc).__name__}: {exc}"
        ) from exc


def _build_local_boundary_proof(context: dict, repo_path: str) -> dict:
    lane = context.get("lane")
    claims = list(context.get("claims") or [])
    holder = context.get("work_claim")
    if not lane or not holder or not claims:
        raise BoundaryProofError(
            "boundary proof needs an active lane, work claim, and path claim"
        )
    try:
        if Path(repo_path).resolve() != Path(str(lane["path"])).resolve():
            raise BoundaryProofError(
                "the proof path is not the item's recorded active lane"
            )
    except OSError as exc:
        raise BoundaryProofError(
            f"the recorded lane path is unreadable: {exc}"
        ) from exc
    head_sha = resolve_worktree_head(repo_path)
    if head_sha != str(lane.get("commit_sha") or ""):
        raise BoundaryProofError(
            "the recorded lane revision is stale; run `yoke project snapshot "
            "sync <LANE> --head-only` and retry"
        )
    targets = sorted({str(claim["integration_target"]) for claim in claims})
    rung_id, template = _local_rung(repo_path, targets)
    declared_paths = sorted(
        {path for claim in claims for path in claim.get("declared_paths") or []}
    )
    checks = []
    integration_bases = []
    for target in targets:
        result = boundary_check_for_paths(
            None,
            project_id=0,
            candidate_paths=declared_paths,
            integration_target=target,
            repo_path=repo_path,
            worktree_head=head_sha,
        )
        if result.status is BoundaryCheckStatus.CONFLICT:
            raise BoundaryProofError(result.diagnostics)
        checks.append(result.to_dict())
        integration_sha = resolve_ref(repo_path, template.format(target=target))
        if not integration_sha:
            raise BoundaryProofError(f"integration ref disappeared for {target!r}")
        integration_bases.append(
            {
                "integration_target": target,
                "integration_base_sha": integration_sha,
                "merge_base_sha": compute_anchor_sha(
                    repo_path=repo_path,
                    integration_target=target,
                    head_sha=head_sha,
                ),
            }
        )
    return {
        "kind": PROOF_KIND,
        "item_id": int(context["item_id"]),
        "rung_id": rung_id,
        "lane": dict(lane),
        "work_claim": dict(holder),
        "claims": list(claims),
        "checks": checks,
        "integration_bases": integration_bases,
    }


def _local_rung(repo_path: str, targets: Sequence[str]) -> tuple[str, str]:
    for rung_id, template in (
        ("remote_integration_ref", REMOTE_INTEGRATION_REF),
        ("local_integration_ref", LOCAL_INTEGRATION_REF),
    ):
        if targets and all(
            resolve_ref(repo_path, template.format(target=target)) for target in targets
        ):
            return rung_id, template
    raise BoundaryProofError(
        "neither remote nor local integration refs resolve for every claim"
    )


def record_boundary_proof(
    conn: Any,
    *,
    item_id: int,
    session_id: str,
    proof: dict,
) -> dict:
    """Validate and durably stamp one caller observation."""
    context = boundary_context(conn, item_id)
    normalized = validate_proof(
        conn,
        context=context,
        proof=proof,
        session_id=session_id,
        verify_remote=True,
    )
    resolution = _proof_resolution(normalized)
    if not record_rung(
        conn,
        item_id=item_id,
        ladder=PATH_CLAIM_BOUNDARY_LADDER,
        resolution=resolution,
        recorded_by_session_id=session_id,
    ):
        raise BoundaryProofError("the boundary proof could not be recorded")
    return normalized


def consume_boundary_proof(
    conn: Any,
    *,
    item_id: int,
    target_status: str,
) -> dict:
    """Return a current hosted proof, or explain exactly why it is unusable."""
    try:
        stamps = read_rungs(conn, item_id)
    except Exception as exc:
        raise BoundaryProofError(
            f"recorded boundary evidence is unreadable: {type(exc).__name__}: {exc}"
        ) from exc
    stamp = next(
        (
            row
            for row in stamps
            if row.get("obligation") == PATH_CLAIM_BOUNDARY_LADDER.obligation
        ),
        None,
    )
    raw = ((stamp or {}).get("facts") or {}).get(PROOF_FACT)
    if not isinstance(raw, str) or not raw:
        raise BoundaryProofError("no caller-produced boundary proof is recorded")
    try:
        proof = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise BoundaryProofError("the recorded boundary proof is unreadable") from exc
    context = boundary_context(conn, item_id)
    normalized = validate_proof(
        conn,
        context=context,
        proof=proof,
        session_id=str((context.get("work_claim") or {}).get("session_id") or ""),
        verify_remote=True,
    )
    if not record_rung(
        conn,
        item_id=item_id,
        ladder=PATH_CLAIM_BOUNDARY_LADDER,
        resolution=_proof_resolution(normalized),
        target_status=target_status,
        recorded_by_session_id=str(
            (context.get("work_claim") or {}).get("session_id") or ""
        ),
    ):
        raise BoundaryProofError("the current boundary proof could not be restamped")
    return normalized


def _proof_resolution(proof: dict) -> LadderResolution:
    rung = PATH_CLAIM_BOUNDARY_LADDER.rung(str(proof["rung_id"]))
    return LadderResolution(
        obligation=PATH_CLAIM_BOUNDARY_LADDER.obligation,
        rung=rung,
        facts={PROOF_FACT: json.dumps(proof, sort_keys=True)},
    )


__all__ = [
    "BoundaryProofError",
    "PROOF_FACT",
    "PROOF_KIND",
    "boundary_context",
    "build_local_boundary_proof",
    "consume_boundary_proof",
    "record_boundary_proof",
]
