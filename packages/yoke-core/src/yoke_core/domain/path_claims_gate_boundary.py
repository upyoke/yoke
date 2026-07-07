"""Lifecycle-gate adapter that runs the boundary check at status writes.

Composed into :func:`yoke_core.domain.backlog_authoritative_status_gate.
_run_authoritative_status_gate` so the boundary check fires at these
gates:

* the gate into ``reviewed-implementation``,
* the gate into ``implemented``, and
* the gate into ``release`` (usher / pre-merge).

The adapter:

* Loads every non-terminal path claim attached to the item.
* Resolves the worktree path from this machine's checkout mapping plus
  the item's recorded worktree branch.
* Runs :func:`yoke_core.domain.path_claims_boundary.boundary_check_for_claim`
  on each claim.
* Blocks the transition with ``GATE_PATH_CLAIM_BOUNDARY`` and the
  rejection diagnostic when any claim returns ``conflict``.

The check is fail-open in three cases that the contract treats as
"nothing to enforce":

* The ``path_claims`` table is absent (minimal-fixture test).
* The item has no worktree branch recorded (planning advances,
  ``--no-worktree`` items, evidence-only items).
* The integration target cannot be resolved in the worktree (no
  remote tracking branch in a fresh test repo).

Fail-open here mirrors the existing gate runners (`db_mutation_gate`)
which opt out on minimal schemas. Real worktrees with a real
integration ref always surface the check.
"""

from __future__ import annotations

from typing import Any, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_checkout_locations import item_worktree_path


_GATED_TARGETS = ("reviewed-implementation", "implemented", "release")
_NON_TERMINAL = ("planned", "blocked", "active")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_repo_path(
    conn: Any, item_id: int
) -> Optional[str]:
    candidate = item_worktree_path(conn, item_id)
    if candidate is None or not candidate.is_dir():
        return None
    return str(candidate)


def _claim_ids_for_item(
    conn: Any, item_id: int
) -> List[int]:
    p = _p(conn)
    try:
        rows = conn.execute(
            "SELECT id FROM path_claims "
            f"WHERE item_id = {p} AND state IN ('planned', 'blocked', 'active') "
            "ORDER BY id",
            (item_id,),
        ).fetchall()
    except db_backend.operational_error_types(conn):
        return []
    return [int(r[0]) for r in rows]


def check_boundary_for_item(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
) -> Optional[dict]:
    """Run boundary checks for every claim attached to the item.

    Returns ``None`` on pass / opt-out. Returns the canonical failure
    payload (``{"success": False, "error_code", "error"}``) when any
    claim's boundary check is ``conflict``.
    """
    if target_status not in _GATED_TARGETS:
        return None

    conn = connect(db_path)
    try:
        repo_path = _resolve_repo_path(conn, item_id)
        if repo_path is None:
            return None
        claim_ids = _claim_ids_for_item(conn, item_id)
        if not claim_ids:
            return None

        try:
            from yoke_core.domain.path_claims_boundary import (
                BoundaryCheckError,
                BoundaryCheckStatus,
                boundary_check_for_claim,
            )
            from yoke_core.domain.path_claims_integration_resolver import (
                IntegrationTargetDiverged,
            )
        except ImportError:  # pragma: no cover - defensive
            return None

        try:
            from yoke_core.domain import path_claims_events as _events
        except ImportError:  # pragma: no cover
            _events = None  # type: ignore[assignment]

        # Aggregate per-claim results into an item-level verdict
        # before rejecting. Single-claim items behave like before
        # (one claim's coverage IS the union); multi-claim items accept
        # when the union of declared coverage covers every touched path,
        # rejecting only when paths are truly out-of-coverage.
        rejections: List[str] = []
        hard_errors: List[str] = []
        per_claim_results = []
        conflict_results = []
        union_declared: set = set()
        union_touched: set = set()
        for claim_id in claim_ids:
            try:
                result = boundary_check_for_claim(
                    conn, claim_id=claim_id, repo_path=repo_path,
                )
            except IntegrationTargetDiverged as exc:
                hard_errors.append(f"claim {claim_id}: {exc}")
                continue
            except BoundaryCheckError:
                continue
            per_claim_results.append((claim_id, result))
            union_declared.update(result.declared_paths or [])
            union_touched.update(result.touched_paths or [])
            if result.status is BoundaryCheckStatus.CONFLICT:
                offending_paths = (
                    result.undeclared_paths or result.uncommitted_paths
                )
                conflict_results.append((claim_id, result, offending_paths))
                rejections.append(
                    f"claim {claim_id} ({result.integration_target}): "
                    f"{result.diagnostics}; offending paths: "
                    f"{', '.join(offending_paths)}"
                )
        # Aggregation: if every touched path is in the union of
        # declared coverage across the item's claims, the item-level
        # verdict is accept even when individual claims reported
        # conflict (they conflicted only because their own coverage was
        # narrower than the union).
        if rejections and len(per_claim_results) > 1:
            residual = union_touched - union_declared
            if not residual:
                rejections = []
        all_rejections = hard_errors + rejections
        if not all_rejections:
            if _events is not None:
                for claim_id, result in per_claim_results:
                    _events.emit_boundary_passed(
                        conn=conn,
                        claim_id=claim_id,
                        integration_target=result.integration_target,
                        status=result.status.value,
                        item_id=item_id,
                    )
            return None
        if _events is not None:
            for claim_id, result, offending_paths in conflict_results:
                _events.emit_boundary_blocked(
                    conn=conn,
                    claim_id=claim_id,
                    integration_target=result.integration_target,
                    diagnostics=result.diagnostics,
                    offending_target_ids=result.undeclared_target_ids,
                    item_id=item_id,
                )
        joined = "\n".join(all_rejections)
        return {
            "success": False,
            "error_code": "GATE_PATH_CLAIM_BOUNDARY",
            "error": (
                f"Path-claim boundary check blocked transition to "
                f"{target_status!r}.\n{joined}\n\n"
                "Remediate by amending the claim (widen) to cover the "
                "committed change, reverting the out-of-scope change, "
                "or splitting the work into a separate item.\n"
                "The claim's recorded activation SHA on "
                "``path_claims.base_commit_sha`` is an audit artifact and "
                "does not gate this verdict: the boundary diff anchors on "
                "the dynamic merge-base of the integration target and the "
                "worktree HEAD."
            ),
        }
    finally:
        conn.close()


__all__ = [
    "check_boundary_for_item",
]
