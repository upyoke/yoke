"""``yoke claims path override`` — operator collision-approval surface."""

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
    "[--conflict-reason REASON] [--item-id N] [--project SLUG] "
    "[--session-id S] [--json]"
)


def claims_path_override(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims path override",
        description=CLAIMS_PATH_OVERRIDE_USAGE,
    )
    parser.add_argument("--claim-id", required=True, help="path_claims.id")
    parser.add_argument(
        "--override-point", required=True,
        choices=("creation", "amend", "revalidation_conflict"),
    )
    parser.add_argument("--integration-target", required=True)
    parser.add_argument("--actor-id", required=True, type=int)
    parser.add_argument("--actor-reason", required=True)
    parser.add_argument("--blocking-claim-id", type=int, default=None)
    parser.add_argument("--blocking-path-targets", default=None)
    parser.add_argument(
        "--conflict-reason", default=None,
        choices=(
            "upstream_delete", "hostile_upstream_touch",
            "claim_overlap", "continuity_unknown",
        ),
    )
    parser.add_argument("--item-id", type=int, default=None)
    parser.add_argument("--project", default=None)
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
    if parsed.item_id is not None:
        payload["item_id"] = int(parsed.item_id)
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
