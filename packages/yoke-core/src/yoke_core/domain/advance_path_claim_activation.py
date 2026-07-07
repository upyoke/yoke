"""Auto-activate path-claim phase for advance preflight.

Runs between the path-claim-required gate (declaration at idea/refine)
and the worktree door-lock check (``state='active'`` at worktree-open).
For every ``path_claims`` row matching ``(item_id, actor_id)`` whose
state is ``planned``, routes through
:func:`yoke_core.domain.path_claims_register.activate_with_events`
with the integration-target snapshot from
:mod:`yoke_core.domain.path_claims_integration_resolver`. Blocked
claims surface a clear error naming the upstream claim id — no
automatic upgrade. Harness-neutral: same logic is reachable from
every harness preflight or direct CLI dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

from yoke_core.domain.advance_path_claim_activation_events import (
    record_blocked_claim,
)
from yoke_core.domain.advance_path_claim_activation_retry import (
    resolve_integration_head_with_retry,
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
            o.claim_id for o in self.outcomes
            if o.state_before == "planned" and o.state_after == "active"
        ]


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _claim_project(
    conn: Any, claim_id: int
) -> tuple[Optional[str], Optional[int]]:
    p = _p(conn)
    row = conn.execute(
        "SELECT p.slug, i.project_id FROM path_claims pc "
        "JOIN items i ON pc.item_id = i.id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        f"WHERE pc.id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None, None
    return (
        str(row[0]) if row[0] else None,
        int(row[1]) if row[1] is not None else None,
    )


def _list_claims_for_session(
    conn: Any, *, item_id: int, actor_id: int
) -> List[Any]:
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, state, blocked_reason, integration_target "
        "FROM path_claims "
        f"WHERE item_id = {p} AND actor_id = {p} "
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
) -> ActivationOutcome:
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
) -> ActivationResult:
    """Activate planned claims for ``(item_id, actor_id)``. Pre-loop,
    legacy coord-only mutex residue (``state='blocked'`` rows the live
    classifier no longer flags) is repaired to ``planned``. Survivors
    surface ``"claim N is blocked by upstream M"`` and emit one
    ``PathClaimActivationBlocked`` event; active claims are no-ops;
    diverged refs surface via :attr:`diverged_error`.
    """
    repair_coordination_only_blocked(conn, item_id=item_id, actor_id=actor_id)
    result = ActivationResult(item_id=item_id, actor_id=actor_id)
    emitted_keys: set = set()
    for row in _list_claims_for_session(
        conn, item_id=item_id, actor_id=actor_id
    ):
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


__all__ = [
    "ActivationOutcome",
    "ActivationResult",
    "check_work_claim_ownership",
    "run_activation_phase",
    "main",
]


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint for advance path-claim activation.

    Resolves the control-plane DB, looks up the item's
    ``COALESCE(owner, source)`` actor, verifies the caller's session
    owns the work claim, then dispatches to
    :func:`run_activation_phase`. Exit codes: ``0`` success (prints
    ``activated=[ids]``); ``1`` blocked/diverged; ``2`` missing item
    / missing actor / invalid argument.
    """
    import argparse
    import os
    import sys
    from yoke_core.domain import db_helpers

    parser = argparse.ArgumentParser(prog="advance_path_claim_activation")
    parser.add_argument("--item", required=True)
    parser.add_argument(
        "--session-id",
        default=(
            os.environ.get("YOKE_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID")
            or os.environ.get("CODEX_THREAD_ID")
            or ""
        ),
        help="Session id for the work-claim ownership check.",
    )
    args = parser.parse_args(argv)
    raw = str(args.item).strip()
    if raw.upper().startswith("YOK-"):
        raw = raw[4:]
    try:
        item_id = int(raw)
    except ValueError:
        print(f"ERROR: invalid --item value: {args.item!r}", file=sys.stderr)
        return 2

    conn = db_helpers.connect()
    try:
        p = _p(conn)
        actor_row = conn.execute(
            f"SELECT COALESCE(owner, source) FROM items WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if actor_row is None:
            print(f"ERROR: item {item_id} not found", file=sys.stderr)
            return 2
        actor_value = actor_row[0]
        if actor_value in (None, ""):
            print(
                "BLOCKED: item has no owner/source actor for "
                "path-claim activation",
                file=sys.stderr,
            )
            return 1
        other_session = check_work_claim_ownership(
            conn, item_id=item_id, session_id=str(args.session_id or ""),
        )
        if other_session:
            print(
                f"BLOCKED: work claim for item {item_id} held by "
                f"session '{other_session}'; activation refused to "
                "avoid stranded path claims",
                file=sys.stderr,
            )
            return 1
        result = run_activation_phase(
            conn,
            item_id=item_id,
            actor_id=int(actor_value),
            session_id=str(args.session_id or "") or None,
        )
    finally:
        conn.close()

    if result.is_blocked:
        if result.diverged_error:
            print(f"DIVERGED: {result.diverged_error}", file=sys.stderr)
        for msg in result.blocked_errors:
            print(f"BLOCKED: {msg}", file=sys.stderr)
        return 1
    print(f"activated={result.activated_claim_ids}")
    return 0


if __name__ == "__main__":
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
