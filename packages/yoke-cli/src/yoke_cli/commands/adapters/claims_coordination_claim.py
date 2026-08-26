"""Read adapter for ``claims.coordination_claim.list``."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


CLAIMS_COORDINATION_CLAIM_LIST_USAGE = (
    "yoke coordination-claim list [--project P] "
    "[--key K] [--session-id S] [--item N] [--active-only] [--json]"
)


def _print_claims(response: Any, stdout, _stderr) -> None:
    claims = (response.result or {}).get("claims") or []
    if not claims:
        print("no coordination claims", file=stdout)
        return
    print(
        "key\ttarget_kind\towner\tclaimed_at\treleased_at",
        file=stdout,
    )
    for claim in claims:
        owner = (
            f"item:{claim.get('owner_item_id')}"
            if claim.get("owner_item_id") is not None
            else (claim.get("session_id") or "")
        )
        print(
            f"{claim.get('key', '')}\t"
            f"{claim.get('target_kind', '')}\t"
            f"{owner}\t"
            f"{claim.get('claimed_at', '')}\t"
            f"{claim.get('released_at') or ''}",
            file=stdout,
        )


def claims_coordination_claim_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke coordination-claim list",
        description=CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument("--key", default=None, help="Filter to one coordination key.")
    parser.add_argument(
        "--session-id", default=None,
        help="Filter to claims held by this session.",
    )
    parser.add_argument(
        "--item", type=int, default=None,
        help="Filter to claims owned by this item id.",
    )
    parser.add_argument(
        "--active-only", action="store_true",
        help="Restrict to claims that have not been released.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project:
        payload["project_id"] = parsed.project
    if parsed.key:
        payload["key"] = parsed.key
    if parsed.session_id:
        payload["session_id"] = parsed.session_id
    if parsed.item:
        payload["owner_item_id"] = parsed.item
    if parsed.active_only:
        payload["active_only"] = True
    return dispatch_and_emit(
        function_id="claims.coordination_claim.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claims,
    )


USAGE_BY_FUNCTION_ID = {
    "claims.coordination_claim.list": CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
}

__all__ = [
    "CLAIMS_COORDINATION_CLAIM_LIST_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_coordination_claim_list",
]
