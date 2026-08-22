"""Standalone CLI entrypoint for path-claim activation.

Sibling of :mod:`yoke_core.domain.advance_path_claim_activation`; the
argparse-driven operator/debug entrypoint lives here so the domain
module (dataclasses, activation loop, guards) stays under the authored
file-line cap. The domain module re-exports :func:`main` so
``python3 -m yoke_core.domain.advance_path_claim_activation`` and
``from ...advance_path_claim_activation import main`` keep working.

The CLI resolves the control-plane DB directly, looks up the item's
``COALESCE(owner, source)`` actor, verifies the caller's session owns
the work claim (refusing when another live session holds it), then
dispatches to :func:`run_activation_phase`. The transport-aware
worktree preflight no longer shells to this CLI — it routes the same
guards through the ``claims.path.activation_run`` function so the
activation works over an https control plane; this module remains the
operator/debug command surface.
"""

from __future__ import annotations

from typing import List, Optional
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id


def main(argv: Optional[List[str]] = None) -> int:
    """Resolve DB + actor, verify ownership, run the activation phase.

    Exit codes: ``0`` success (prints ``activated=[ids]``); ``1``
    blocked/diverged; ``2`` missing item / missing actor / invalid
    argument.
    """
    import argparse
    import sys

    from yoke_core.domain import db_helpers
    from yoke_core.domain.advance_path_claim_activation import (
        check_work_claim_ownership,
        resolve_item_actor,
        run_activation_phase,
    )
    from yoke_core.domain.yok_n_parser import parse_item_argument

    parser = argparse.ArgumentParser(prog="advance_path_claim_activation")
    parser.add_argument("--item", required=True)
    parser.add_argument(
        "--session-id",
        default=resolve_ambient_session_id() or "",
        help="Session id for the work-claim ownership check.",
    )
    args = parser.parse_args(argv)
    conn = db_helpers.connect()
    try:
        try:
            item_id = parse_item_argument(args.item, conn=conn)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        actor_id, actor_error = resolve_item_actor(conn, item_id)
        if actor_error is not None:
            prefix = "ERROR" if "not found" in actor_error else "BLOCKED"
            print(f"{prefix}: {actor_error}", file=sys.stderr)
            return 2 if prefix == "ERROR" else 1
        other_session = check_work_claim_ownership(
            conn,
            item_id=item_id,
            session_id=str(args.session_id or ""),
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
            actor_id=int(actor_id),
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


__all__ = ["main"]


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv[1:]))
