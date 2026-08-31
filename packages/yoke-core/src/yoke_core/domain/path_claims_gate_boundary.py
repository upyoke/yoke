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

The gate never passes on an unexamined boundary. An item with zero
non-terminal claims has genuinely nothing to enforce and returns clear;
every other shortage is a named refusal:

* The ``path_claims`` table cannot be read — the control plane cannot
  say whether coverage was declared, which is not the same as no
  coverage being declared.
* The item holds claims but has no resolvable worktree — there is no
  committed tree to compare the coverage against.
* Neither integration ref resolves — see
  :mod:`yoke_core.domain.path_claims_boundary_ladder`, which owns the
  ordered ladder (remote ref, then local ref) and the refusal narrative.

When a rung does resolve, the item records which one through
:func:`yoke_core.domain.gate_satisfier_stamp.record_rung`, so a reader
can later tell a boundary proved against the shared remote from one
proved against a local trunk.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.gate_satisfier_ladder import LadderUnsatisfied
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    PATH_CLAIM_BOUNDARY_LADDER,
)
from yoke_core.domain.gate_satisfier_stamp import record_refusal, record_rung
from yoke_core.domain.path_claims_boundary_ladder import resolve_boundary_rung
from yoke_core.domain.project_checkout_locations import item_worktree_path
from yoke_core.domain.project_identity import render_item_ref


_GATED_TARGETS = ("reviewed-implementation", "implemented", "release")
_NON_TERMINAL = ("planned", "blocked", "active")


class PinnedPathClaimPolicyUnreadable(RuntimeError):
    """A real workflow pin exists but cannot resolve to a policy."""


class PathClaimsUnreadable(RuntimeError):
    """The claim rows themselves could not be read for this item."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _blocked(message: str) -> dict:
    """Render the canonical block payload for this gate."""
    return {
        "success": False,
        "error_code": "GATE_PATH_CLAIM_BOUNDARY",
        "error": message,
    }


def _project_id(conn: Any, item_id: int) -> int:
    p = _p(conn)
    row = conn.execute(
        f"SELECT project_id FROM items WHERE id = {p}", (item_id,)
    ).fetchone()
    if row is None:
        raise PathClaimsUnreadable(
            f"item {item_id} has no row in items; the boundary gate cannot "
            "resolve the project whose facts the integration ladder needs"
        )
    return int(row[0])


def _resolve_repo_path(conn: Any, item_id: int) -> Optional[str]:
    candidate = item_worktree_path(conn, item_id)
    if candidate is None or not candidate.is_dir():
        return None
    return str(candidate)


def _claims_for_item(conn: Any, item_id: int) -> List[Tuple[int, str]]:
    p = _p(conn)
    try:
        from yoke_core.domain.path_claim_task_bindings import (
            pinned_task_claim_policy,
        )

        task_scoped = pinned_task_claim_policy(conn, item_id)
    except Exception as exc:
        raise PinnedPathClaimPolicyUnreadable(
            f"cannot resolve pinned path-claim policy for "
            f"{render_item_ref(conn, item_id)}: {exc}"
        ) from exc
    try:
        if task_scoped:
            rows = conn.execute(
                "SELECT DISTINCT pc.id, pc.integration_target FROM path_claims pc "
                "JOIN path_claim_task_bindings b ON b.claim_id = pc.id "
                f"WHERE b.epic_id = {p} "
                "AND pc.state IN ('planned', 'blocked', 'active') "
                "ORDER BY pc.id",
                (item_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, integration_target FROM path_claims "
                f"WHERE owner_kind = 'item' AND owner_item_id = {p} "
                "AND state IN ('planned', 'blocked', 'active') "
                "ORDER BY id",
                (item_id,),
            ).fetchall()
    except db_backend.operational_error_types(conn) as exc:
        raise PathClaimsUnreadable(
            f"cannot read path claims for {render_item_ref(conn, item_id)}: "
            f"{exc}. The control plane could not say whether this item "
            "declared coverage, which is not the same as it declaring none, "
            "so the boundary is refused rather than passed. Converge the "
            "schema (restart the server, which applies the pending schema on "
            "boot) and retry the transition."
        ) from exc
    return [(int(r[0]), str(r[1] or "")) for r in rows]


def check_boundary_for_item(
    *,
    item_id: int,
    target_status: str,
    db_path: str,
    definition_selected: bool = False,
) -> Optional[dict]:
    """Run boundary checks for every claim attached to the item.

    Returns ``None`` when the item declares no coverage to enforce.
    Returns the canonical failure payload
    (``{"success": False, "error_code", "error"}``) when a claim's
    boundary check is ``conflict``, when the claims cannot be read, when
    the item has claims but no worktree, or when no rung of the
    integration ladder is reachable.
    """
    if not definition_selected and target_status not in _GATED_TARGETS:
        return None

    conn = connect(db_path)
    try:
        try:
            claims = _claims_for_item(conn, item_id)
        except (PinnedPathClaimPolicyUnreadable, PathClaimsUnreadable) as exc:
            return _blocked(str(exc))
        if not claims:
            return None
        claim_ids = [claim_id for claim_id, _target in claims]

        repo_path = _resolve_repo_path(conn, item_id)
        if repo_path is None:
            return _blocked(
                f"{render_item_ref(conn, item_id)} holds "
                f"{len(claim_ids)} active path claim(s) but has no resolvable "
                "worktree on this machine, so the committed change cannot be "
                "compared against the coverage it declared.\n\n"
                "Remediate by preparing the item's lane "
                "(`yoke direct-workflow worktree prepare <ITEM>`), repairing "
                "the recorded path (`yoke item-worktrees path-record`), or "
                "releasing the claims if this item no longer edits files. "
                "The gate does not pass here: an unchecked boundary and a "
                "clean boundary are not the same answer."
            )

        try:
            resolution = resolve_boundary_rung(
                conn,
                project_id=_project_id(conn, item_id),
                item_id=item_id,
                repo_path=repo_path,
                integration_targets=[target for _cid, target in claims],
            )
        except PathClaimsUnreadable as exc:
            return _blocked(str(exc))
        except LadderUnsatisfied as exc:
            record_refusal(
                conn,
                item_id=item_id,
                ladder=PATH_CLAIM_BOUNDARY_LADDER,
                resolution=exc.resolution,
                target_status=target_status,
            )
            return _blocked(exc.message)

        try:
            from yoke_core.domain.path_claims_boundary import (
                BoundaryCheckError,
                BoundaryCheckStatus,
                boundary_check_for_claim,
            )
            from yoke_core.domain.path_claims_integration_resolver import (
                IntegrationTargetDiverged,
            )
        except ImportError as exc:  # pragma: no cover - defensive
            return _blocked(
                "the path-claim boundary implementation could not be "
                f"imported ({exc}); this build cannot evaluate the boundary "
                "it is being asked to enforce. Reinstall or repair the Yoke "
                "engine on this machine and retry."
            )

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
                    conn,
                    claim_id=claim_id,
                    repo_path=repo_path,
                )
            except IntegrationTargetDiverged as exc:
                hard_errors.append(f"claim {claim_id}: {exc}")
                continue
            except BoundaryCheckError as exc:
                hard_errors.append(
                    f"claim {claim_id}: boundary check could not run: {exc}"
                )
                continue
            per_claim_results.append((claim_id, result))
            union_declared.update(result.declared_paths or [])
            union_touched.update(result.touched_paths or [])
            if result.status is BoundaryCheckStatus.CONFLICT:
                offending_paths = result.undeclared_paths or result.uncommitted_paths
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
            record_rung(
                conn,
                item_id=item_id,
                ladder=PATH_CLAIM_BOUNDARY_LADDER,
                resolution=resolution,
                target_status=target_status,
            )
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
    "PathClaimsUnreadable",
    "PinnedPathClaimPolicyUnreadable",
    "check_boundary_for_item",
]
