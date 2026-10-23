"""``yoke claims path override`` — steering collision-approval surface."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


CLAIMS_PATH_OVERRIDE_USAGE = (
    "yoke claims path override --claim-id N "
    "--override-point creation|amend|revalidation_conflict "
    "--integration-target TARGET --actor-id N --actor-reason TEXT "
    "[--blocking-claim-id M] [--blocking-path-targets ID,ID,...] "
    "[--conflict-reason REASON] [--item PREFIX-N] [--project SLUG] "
    "[--session-id S] [--json]"
)


def claims_path_override(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path override",
        usage=CLAIMS_PATH_OVERRIDE_USAGE,
    )
    parser.add_argument(
        "--claim-id", required=True, help="Path claim to approve the collision for."
    )
    parser.add_argument(
        "--override-point",
        required=True,
        choices=("creation", "amend", "revalidation_conflict"),
        help="Claim step where the collision happened.",
    )
    parser.add_argument(
        "--integration-target", required=True, help="Branch the claim merges into."
    )
    parser.add_argument(
        "--actor-id", required=True, type=int, help="Id of the person approving."
    )
    parser.add_argument(
        "--actor-reason", required=True, help="Why the collision is approved."
    )
    parser.add_argument(
        "--blocking-claim-id",
        type=int,
        default=None,
        help="Path claim that collides with this one.",
    )
    parser.add_argument(
        "--blocking-path-targets",
        default=None,
        help="Comma-separated ids of the colliding path targets.",
    )
    parser.add_argument(
        "--conflict-reason",
        default=None,
        choices=(
            "upstream_delete",
            "hostile_upstream_touch",
            "claim_overlap",
            "continuity_unknown",
        ),
        help="Kind of collision being approved.",
    )
    parser.add_argument("--item", default=None, help="Item the claim belongs to.")
    parser.add_argument("--project", default=None, help="Project scope.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CLAIMS_PATH_OVERRIDE_USAGE)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError as exc:
        return usage_error(str(exc))

    payload = {
        "path_claim_id": claim_id,
        "override_point": parsed.override_point,
        "integration_target": parsed.integration_target,
        "actor_id": int(parsed.actor_id),
        "actor_reason": parsed.actor_reason,
    }
    if parsed.blocking_claim_id is not None:
        payload["blocking_claim_id"] = int(parsed.blocking_claim_id)
    if parsed.blocking_path_targets:
        payload["blocking_path_targets"] = [
            int(x) for x in split_comma(parsed.blocking_path_targets)
        ]
    if parsed.conflict_reason:
        payload["conflict_reason"] = parsed.conflict_reason
    if parsed.item is not None:
        payload["public_ref"] = parsed.item
    if parsed.project:
        payload["project"] = parsed.project

    return dispatch_and_emit(
        function_id="claims.path.override",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = ["CLAIMS_PATH_OVERRIDE_USAGE", "claims_path_override"]
