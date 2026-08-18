"""Read adapter for ``claims.coordination_lease.list``."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


CLAIMS_COORDINATION_LEASE_LIST_USAGE = (
    "yoke coordination-lease list [--project P] "
    "[--key K] [--session-id S] [--item N] [--active-only] [--json]"
)


def _print_leases(response: Any, stdout, _stderr) -> None:
    leases = (response.result or {}).get("leases") or []
    if not leases:
        print("no coordination leases", file=stdout)
        return
    print(
        "lease_key\towner_kind\towner\tacquired_at\treleased_at",
        file=stdout,
    )
    for lease in leases:
        owner = (
            f"item:{lease.get('owner_item_id')}"
            if lease.get("owner_kind") == "item"
            else (lease.get("owner_session_id") or lease.get("session_id") or "")
        )
        print(
            f"{lease.get('lease_key', '')}\t"
            f"{lease.get('owner_kind', '')}\t"
            f"{owner}\t"
            f"{lease.get('acquired_at', '')}\t"
            f"{lease.get('released_at') or ''}",
            file=stdout,
        )


def claims_coordination_lease_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke coordination-lease list",
        description=CLAIMS_COORDINATION_LEASE_LIST_USAGE,
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument("--key", default=None, help="Filter to one lease key.")
    parser.add_argument(
        "--session-id", default=None,
        help="Filter to session-owned leases for this session.",
    )
    parser.add_argument(
        "--item", type=int, default=None,
        help="Filter to item-owned leases for this item id.",
    )
    parser.add_argument(
        "--active-only", action="store_true",
        help="Restrict to leases that have not been released.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CLAIMS_COORDINATION_LEASE_LIST_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project:
        payload["project_id"] = parsed.project
    if parsed.key:
        payload["lease_key"] = parsed.key
    if parsed.session_id:
        payload["session_id"] = parsed.session_id
    if parsed.item:
        payload["owner_item_id"] = parsed.item
    if parsed.active_only:
        payload["active_only"] = True
    return dispatch_and_emit(
        function_id="claims.coordination_lease.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_leases,
    )


USAGE_BY_FUNCTION_ID = {
    "claims.coordination_lease.list": CLAIMS_COORDINATION_LEASE_LIST_USAGE,
}

__all__ = [
    "CLAIMS_COORDINATION_LEASE_LIST_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_coordination_lease_list",
]
