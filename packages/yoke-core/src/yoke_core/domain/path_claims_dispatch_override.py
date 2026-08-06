"""``path-claims override`` CLI handler.

Routes through the registered ``claims.path.override`` function so the
operator surface works over an https control plane. The legacy
``service_client path-claim-override`` entry still reaches this module;
both paths must relay rather than bare-connect.

Usage:

  path-claims override <claim_id>
    --override-point creation|amend|revalidation_conflict
    --integration-target main
    --actor-id N
    --actor-reason "<non-empty operator-authored reason>"
    [--blocking-claim-id M]
    [--blocking-path-targets ID,ID,...]
    [--conflict-reason upstream_delete|hostile_upstream_touch|claim_overlap|continuity_unknown]

Returns exit codes:

  0  override emitted
  1  validation error (claim missing, empty reason, invalid enum, hook context)
  2  argument parsing failure
"""

from __future__ import annotations

import argparse
from typing import List, Sequence

from yoke_core.domain.path_claims_dispatch_io import print_error, print_json


def _parse_int_list(raw: str) -> List[int]:
    return [int(p) for p in raw.split(",") if p.strip()]


def cmd_override(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="path-claims override", add_help=False,
    )
    parser.add_argument("claim_id", type=int)
    parser.add_argument(
        "--override-point", required=True,
        choices=("creation", "amend", "revalidation_conflict"),
    )
    parser.add_argument("--integration-target", required=True)
    parser.add_argument("--actor-id", type=int, required=True)
    parser.add_argument("--actor-reason", required=True)
    parser.add_argument("--blocking-claim-id", type=int, default=None)
    parser.add_argument(
        "--blocking-path-targets", default="",
        help=(
            "Comma-separated path_targets ids representing the anchor "
            "roots involved in the collision (NOT a full descendant "
            "enumeration)."
        ),
    )
    parser.add_argument(
        "--conflict-reason", default=None,
        choices=(
            None, "upstream_delete", "hostile_upstream_touch",
            "claim_overlap", "continuity_unknown",
        ),
    )
    parser.add_argument("--item-id", type=int, default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--session-id", default=None)
    try:
        args = parser.parse_args(list(argv))
    except SystemExit:
        print_error("USAGE", "see --help for path-claims override")
        return 2

    from yoke_contracts.api.function_call import ActorContext, TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    payload = {
        "path_claim_id": args.claim_id,
        "override_point": args.override_point,
        "integration_target": args.integration_target,
        "actor_id": args.actor_id,
        "actor_reason": args.actor_reason,
        "blocking_claim_id": args.blocking_claim_id,
        "blocking_path_targets": (
            _parse_int_list(args.blocking_path_targets)
            if args.blocking_path_targets
            else []
        ),
        "conflict_reason": args.conflict_reason,
        "item_id": args.item_id,
        "project": args.project,
    }
    actor = ActorContext(session_id=args.session_id or "")
    response = call_dispatcher(
        function_id="claims.path.override",
        target=TargetRef(kind="global"),
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = (
            response.error.code if response.error is not None else "override_failed"
        )
        message = (
            response.error.message if response.error is not None else "override failed"
        )
        print_error(str(code).upper(), message, claim_id=args.claim_id)
        return 1

    result = response.result or {}
    print_json({
        "success": True,
        "event_id": result.get("override_event_id"),
        "claim_id": args.claim_id,
        "blocking_claim_id": args.blocking_claim_id,
        "override_point": args.override_point,
    })
    return 0


__all__ = ["cmd_override"]
