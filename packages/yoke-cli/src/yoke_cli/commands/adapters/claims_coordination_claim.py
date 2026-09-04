"""CLI adapters for the ``claims.coordination_claim.*`` family."""

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
CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE = (
    "yoke claims coordination-claim acquire --project P --key K "
    "[--reason TEXT] [--item N] [--json]"
)
CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE = (
    "yoke claims coordination-claim release (--project P --key K | "
    "--claim-id N) --reason TEXT [--json]"
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


def _print_claim(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    print(
        f"{claim.get('key', '')}\t"
        f"claim_id={claim.get('id', '')}\t"
        f"session={claim.get('session_id', '')}\t"
        f"claimed_at={claim.get('claimed_at', '')}\t"
        f"released_at={claim.get('released_at') or ''}",
        file=stdout,
    )


def claims_coordination_claim_acquire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims coordination-claim acquire",
        description=CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE,
        epilog=(
            "Takes one shared-operation claim for this session. The deploy "
            "lock is DEPLOY:<project-slug>: hold it while driving a release "
            "pair, and release it when the pair completes. Reserved "
            "qualification grants open only through session-control."
        ),
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument("--key", required=True, help="Coordination key.")
    parser.add_argument(
        "--reason", default=None, help="Why this session is taking the claim.",
    )
    parser.add_argument(
        "--item", type=int, default=None,
        help="Owning item id, for the kinds whose scope records one.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"project_id": parsed.project, "key": parsed.key}
    if parsed.reason:
        payload["reason"] = parsed.reason
    if parsed.item:
        payload["item_id"] = parsed.item
    return dispatch_and_emit(
        function_id="claims.coordination_claim.acquire",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claim,
    )


def claims_coordination_claim_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims coordination-claim release",
        description=CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE,
        epilog=(
            "Releases a claim by the (project, key) that addresses it, or by "
            "row id. This is the holder's own release; freeing a claim "
            "stranded by another session is the human-only "
            "`yoke coordination-claim release`, which records an "
            "OperatorLeaseRelease event."
        ),
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument("--key", default=None, help="Coordination key.")
    parser.add_argument(
        "--claim-id", type=int, default=None, help="Claim row id.",
    )
    parser.add_argument("--reason", required=True, help="Why it is released.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.claim_id is None and not (parsed.project and parsed.key):
        print(f"usage: {CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE}")
        return 2
    payload: Dict[str, Any] = {"reason": parsed.reason}
    if parsed.claim_id is not None:
        payload["claim_id"] = parsed.claim_id
    else:
        payload["project_id"] = parsed.project
        payload["key"] = parsed.key
    return dispatch_and_emit(
        function_id="claims.coordination_claim.release",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claim,
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
    "claims.coordination_claim.acquire": (
        CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE
    ),
    "claims.coordination_claim.list": CLAIMS_COORDINATION_CLAIM_LIST_USAGE,
    "claims.coordination_claim.release": (
        CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE
    ),
}

__all__ = [
    "CLAIMS_COORDINATION_CLAIM_ACQUIRE_USAGE",
    "CLAIMS_COORDINATION_CLAIM_LIST_USAGE",
    "CLAIMS_COORDINATION_CLAIM_RELEASE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_coordination_claim_acquire",
    "claims_coordination_claim_list",
    "claims_coordination_claim_release",
]
