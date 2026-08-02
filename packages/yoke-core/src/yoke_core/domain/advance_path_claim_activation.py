"""Auto-activate path-claim phase for advance preflight.

Runs between the path-claim-required gate (declaration at idea/refine)
and the worktree door-lock check (``state='active'`` at worktree-open).
Planned rows route through the canonical activation/event surface.
Blocked rows name the upstream claim instead of upgrading automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional

from yoke_core.domain.advance_path_claim_activation_events import (
    record_blocked_claim,
)
from yoke_core.domain.advance_path_claim_activation_retry import (
    resolve_integration_head_with_retry,
)
from yoke_core.domain.advance_path_claim_task_activation import (
    task_activation_block_reason,
)
from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import PathClaimError, get_claim
from yoke_core.domain.path_claims_blocked_coordination_repair import (
    repair_coordination_only_blocked,
)
from yoke_core.domain.path_claims_register import activate_with_events
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


@dataclass
class ActivationOutcome:
    claim_id: int
    state_before: str
    state_after: str
    commit_sha: Optional[str] = None
    error: Optional[str] = None


@dataclass
class ActivationResult:
    item_id: int
    actor_id: int
    outcomes: List[ActivationOutcome] = field(default_factory=list)
    blocked_errors: List[str] = field(default_factory=list)
    diverged_error: Optional[str] = None

    @property
    def is_blocked(self) -> bool:
        return bool(self.blocked_errors) or self.diverged_error is not None

    @property
    def activated_claim_ids(self) -> List[int]:
        return [
            o.claim_id
            for o in self.outcomes
            if o.state_before == "planned" and o.state_after == "active"
        ]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_project(conn: Any, claim_id: int) -> tuple[Optional[str], Optional[int]]:
    p = _p(conn)
    row = conn.execute(
        "SELECT p.slug, i.project_id FROM path_claims pc "
        "JOIN items i ON pc.owner_item_id = i.id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE pc.id = {p} AND pc.owner_kind = 'item'",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None, None
    return (
        str(row[0]) if row[0] else None,
        int(row[1]) if row[1] is not None else None,
    )


def _list_claims_for_session(conn: Any, *, item_id: int, actor_id: int) -> List[Any]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, state, blocked_reason, integration_target "
        "FROM path_claims "
        f"WHERE owner_kind = 'item' AND owner_item_id = {p} "
        f"AND registered_by_actor_id = {p} "
        "AND state NOT IN ('released', 'cancelled') "
        "ORDER BY id",
        (item_id, actor_id),
    ).fetchall()
    return list(rows)


def _activate_one(
    conn: Any,
    *,
    claim_id: int,
    integration_target: str,
    resolved_head: Optional[str] = None,
) -> ActivationOutcome:
    # ``resolved_head`` is the integration-target head resolved by the
    # caller from its machine-local checkout. The server has no checkout
    # over an https transport, so the transport-aware worktree preflight
    # resolves the head client-side and supplies it here. When it is
    # absent (the in-process CLI path and any direct caller), resolve it
    # locally exactly as before — the checkout is present on that host.
    if resolved_head:
        commit_sha: Optional[str] = resolved_head
    else:
        project_slug, numeric_project_id = _claim_project(conn, claim_id)
        checkout = checkout_for_project_id(numeric_project_id)
        if not project_slug or checkout is None:
            return ActivationOutcome(
                claim_id=claim_id,
                state_before="planned",
                state_after="planned",
                error=(
                    "claim's item has no machine-local checkout mapping; "
                    "cannot resolve integration head"
                ),
            )
        # Backend lock errors are bounded-retried in the sibling helper;
        # surviving lock failures surface with the db-lock: prefix so the
        # block-kind classifier can tag them as
        # BLOCK_DB_LOCK rather than BLOCK_PATH_CLAIM.
        rr = resolve_integration_head_with_retry(
            conn,
            project_id=project_slug,
            repo_path=str(checkout),
            integration_target=integration_target,
        )
        if rr.error is not None:
            return ActivationOutcome(
                claim_id=claim_id,
                state_before="planned",
                state_after="planned",
                error=rr.error,
            )
        commit_sha = rr.commit_sha
    try:
        activate_with_events(
            conn,
            claim_id=claim_id,
            base_commit_sha=commit_sha,
            upstream_claim_id=None,
        )
    except PathClaimError as exc:
        return ActivationOutcome(
            claim_id=claim_id,
            state_before="planned",
            state_after="planned",
            commit_sha=commit_sha,
            error=str(exc),
        )
    refreshed = get_claim(conn, claim_id)
    return ActivationOutcome(
        claim_id=claim_id,
        state_before="planned",
        state_after=str(refreshed["state"]),
        commit_sha=commit_sha,
    )


def run_activation_phase(
    conn: Any,
    *,
    item_id: int,
    actor_id: int,
    session_id: Optional[str] = None,
    resolved_heads: Optional[Mapping[int, str]] = None,
) -> ActivationResult:
    """Activate planned claims for ``(item_id, actor_id)``. Pre-loop,
    legacy coord-only mutex residue (``state='blocked'`` rows the live
    classifier no longer flags) is repaired to ``planned``. Survivors
    surface ``"claim N is blocked by upstream M"`` and emit one
    ``PathClaimActivationBlocked`` event; active claims are no-ops;
    diverged refs surface via :attr:`diverged_error`.

    ``resolved_heads`` maps ``claim_id -> integration-target head SHA``
    resolved by the caller from its machine-local checkout. When a head
    is supplied for a claim it is used directly (the https path, where
    the server has no checkout); when absent the head is resolved
    locally (the in-process path). Keys for claims that are not
    activated are ignored, so an over-provisioned map is harmless.
    """
    heads = {int(k): str(v) for k, v in (resolved_heads or {}).items()}
    result = ActivationResult(item_id=item_id, actor_id=actor_id)
    task_block = task_activation_block_reason(conn, item_id)
    if task_block:
        result.blocked_errors.append(task_block)
        return result
    repair_coordination_only_blocked(conn, item_id=item_id, actor_id=actor_id)
    emitted_keys: set = set()
    for row in _list_claims_for_session(conn, item_id=item_id, actor_id=actor_id):
        claim_id = int(row[0])
        state = str(row[1])
        blocked_reason = row[2]
        integration_target = str(row[3])
        if state == "active":
            result.outcomes.append(
                ActivationOutcome(
                    claim_id=claim_id,
                    state_before=state,
                    state_after=state,
                )
            )
            continue
        if state == "blocked":
            record_blocked_claim(
                conn,
                result=result,
                outcome_cls=ActivationOutcome,
                claim_id=claim_id,
                blocked_reason=blocked_reason,
                item_id=item_id,
                session_id=session_id,
                emitted_keys=emitted_keys,
            )
            continue
        if state != "planned":
            continue
        outcome = _activate_one(
            conn,
            claim_id=claim_id,
            integration_target=integration_target,
            resolved_head=heads.get(claim_id),
        )
        result.outcomes.append(outcome)
        if outcome.error:
            if "diverged" in outcome.error:
                result.diverged_error = outcome.error
            else:
                result.blocked_errors.append(
                    f"claim {claim_id} activation failed: {outcome.error}"
                )
    return result


def check_work_claim_ownership(
    conn: Any, *, item_id: int, session_id: str
) -> Optional[str]:
    """Return a conflicting session id when activation must refuse.

    Standalone activation must not flip planned
    claims to active when another live session owns the item's work
    claim. Returns ``None`` when no live exclusive item claim exists,
    when ``session_id`` itself owns it, or when ``session_id`` is
    empty (CLI flows without a known identity skip the check).
    Otherwise returns the other session's id.
    """
    if not session_id:
        return None
    p = _p(conn)
    row = conn.execute(
        "SELECT session_id FROM work_claims "
        f"WHERE target_kind='item' AND item_id={p} "
        "AND released_at IS NULL AND claim_type='exclusive' "
        "ORDER BY claimed_at DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    if row is None:
        return None
    other = str(row[0])
    return None if other == session_id else other


def resolve_item_actor(
    conn: Any, item_id: int
) -> tuple[Optional[int], Optional[str]]:
    """Resolve an item's owning actor as ``COALESCE(owner, source)``.

    Returns ``(actor_id, None)`` on success or ``(None, error)`` when
    the item is missing or carries no owner/source actor for path-claim
    activation. The activation loop filters ``path_claims`` by this
    actor, so the owning actor — not the calling session's actor — is
    the correct scope. Shared by the CLI entrypoint and the
    ``claims.path.activation_run`` handler so the resolution lives in
    one place.
    """
    p = _p(conn)
    row = conn.execute(
        f"SELECT COALESCE(owner, source) FROM items WHERE id = {p}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None, f"item {item_id} not found"
    actor_value = row[0]
    if actor_value in (None, ""):
        return None, "item has no owner/source actor for path-claim activation"
    return int(actor_value), None


# CLI entrypoint lives in the sibling module to keep this file under the
# authored file-line cap; re-exported so ``main`` and the ``-m`` module
# path stay callable from here.
from yoke_core.domain.advance_path_claim_activation_cli import main  # noqa: E402


__all__ = [
    "ActivationOutcome",
    "ActivationResult",
    "check_work_claim_ownership",
    "resolve_item_actor",
    "run_activation_phase",
    "main",
]


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv[1:]))
