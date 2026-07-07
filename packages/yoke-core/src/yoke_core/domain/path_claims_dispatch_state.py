"""Activation / release / cancel CLI handlers for ``path-claims``.

Kept outside :mod:`path_claims_dispatch` so the top-level dispatcher
stays a small router while this module owns the state-transition
details, including the activation snapshot lookup.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain import path_claims_events as _events
from yoke_core.domain.path_claims import PathClaimError, get_claim
from yoke_core.domain.path_claims_boundary_git import (
    BoundaryCheckError,
)
from yoke_core.domain.path_claims_dispatch_io import (
    open_conn,
    print_error,
    print_json,
)
from yoke_core.domain.path_claims_dispatch_ownership import deny_if_not_owner
from yoke_core.domain.path_claims_integration_resolver import (
    IntegrationTargetDiverged,
    resolve_integration_head_with_divergence_check,
)
from yoke_core.domain.path_claims_read import claim_projection
from yoke_core.domain.path_claims_register import activate_with_events
from yoke_core.domain.project_checkout_locations import checkout_for_project_id


def _claim_project_and_repo(conn, claim_id: int) -> tuple[Optional[int], Optional[str]]:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        "SELECT i.project_id FROM path_claims pc "
        "JOIN items i ON pc.item_id = i.id "
        f"WHERE pc.id = {p}",
        (claim_id,),
    ).fetchone()
    if row is None:
        return None, None
    project_id = int(row[0]) if row[0] else None
    checkout = checkout_for_project_id(project_id)
    return project_id, str(checkout) if checkout is not None else None


def _commit_sha_for_activation(
    conn,
    *,
    claim_id: int,
    repo_path_override: Optional[str],
    explicit_base_commit_sha: Optional[str],
) -> str:
    if explicit_base_commit_sha:
        return str(explicit_base_commit_sha)
    claim = get_claim(conn, claim_id)
    project_id, repo_path = _claim_project_and_repo(conn, claim_id)
    repo_path = repo_path_override or repo_path
    if not project_id or not repo_path:
        raise BoundaryCheckError(
            "activation needs --base-commit-sha or an item-linked project "
            "with a machine-local checkout mapping"
        )
    # Route through the deliberate resolver: origin-then-local with
    # divergence detection. Divergent refs raise before any DB mutation.
    return resolve_integration_head_with_divergence_check(
        conn,
        project_id=project_id,
        repo_path=repo_path,
        integration_target=str(claim["integration_target"]),
    )


def cmd_activate(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="path-claims activate", add_help=False)
    parser.add_argument("claim_id", type=int)
    parser.add_argument("--base-commit-sha", default=None)
    parser.add_argument("--upstream-claim-id", type=int, default=None)
    parser.add_argument(
        "--repo-path",
        default=None,
        help="Override project repo path when deriving the base commit SHA.",
    )
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        print_error("USAGE", "see --help for path-claims activate")
        return 2
    conn = open_conn()
    try:
        if deny_if_not_owner(conn, action="activate", claim_id=args.claim_id):
            return 1
        try:
            base_commit_sha = _commit_sha_for_activation(
                conn,
                claim_id=args.claim_id,
                repo_path_override=args.repo_path,
                explicit_base_commit_sha=args.base_commit_sha,
            )
            activate_with_events(
                conn,
                claim_id=args.claim_id,
                base_commit_sha=base_commit_sha,
                upstream_claim_id=args.upstream_claim_id,
            )
            projection = claim_projection(conn, args.claim_id)
        except IntegrationTargetDiverged as exc:
            print_error("DIVERGED", str(exc), claim_id=args.claim_id)
            return 1
        except BoundaryCheckError as exc:
            print_error("BOUNDARY_IO", str(exc), claim_id=args.claim_id)
            return 1
        except PathClaimError as exc:
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    print_json({"success": True, "claim": projection})
    return 0


def _claim_state_change(argv: Sequence[str], action: str) -> int:
    parser = argparse.ArgumentParser(prog=f"path-claims {action}", add_help=False)
    parser.add_argument("claim_id", type=int)
    parser.add_argument("--reason", required=True)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        print_error("USAGE", f"Usage: path-claims {action} <claim-id> --reason R")
        return 2
    conn = open_conn()
    try:
        if deny_if_not_owner(conn, action=action, claim_id=args.claim_id):
            return 1
        try:
            from yoke_core.domain.path_claims import (
                cancel as cancel_claim,
                release as release_claim,
            )

            if action == "release":
                release_claim(conn, claim_id=args.claim_id, reason=args.reason)
            elif action == "cancel":
                cancel_claim(conn, claim_id=args.claim_id, reason=args.reason)
            else:  # pragma: no cover - defensive
                print_error("USAGE", f"unknown action {action!r}")
                return 2
            projection = claim_projection(conn, args.claim_id)
            if action == "release":
                _events.emit_released(
                    conn=conn, claim=projection, reason=args.reason,
                )
                # Re-classify downstream blocked claims via
                # both direct blocked_reason references and
                # item_dependencies satisfaction.
                from yoke_core.domain.path_claims_dependency_propagation \
                    import propagate_release_unblock
                propagate_release_unblock(
                    conn, released_claim_id=args.claim_id,
                )
            elif action == "cancel":
                _events.emit_cancelled(
                    conn=conn, claim=projection, reason=args.reason,
                )
        except PathClaimError as exc:
            print_error("VALIDATION", str(exc), claim_id=args.claim_id)
            return 1
    finally:
        conn.close()
    print_json({"success": True, "claim": projection})
    return 0


def cmd_release(argv: Sequence[str]) -> int:
    return _claim_state_change(argv, "release")


def cmd_cancel(argv: Sequence[str]) -> int:
    return _claim_state_change(argv, "cancel")


__all__ = [
    "cmd_activate",
    "cmd_cancel",
    "cmd_release",
]
