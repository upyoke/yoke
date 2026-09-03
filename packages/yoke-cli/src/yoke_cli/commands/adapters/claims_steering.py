"""CLI adapters for the ``claims.steering.*`` family."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_contracts.steering_claims import DEFAULT_STEERING_DOC_SLUG
from yoke_cli.commands._helpers import (
    add_json_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


STEERING_ACQUIRE_USAGE = (
    "yoke claims steering acquire --project P [--doc SLUG] [--reason TEXT] [--json]"
)
STEERING_RELEASE_USAGE = "yoke claims steering release CLAIM_ID --reason TEXT [--json]"
STEERING_LIST_USAGE = (
    "yoke claims steering list [--project P] [--session-id S] [--active-only] [--json]"
)


def _project_id(claim: Dict[str, Any]) -> Any:
    scope = claim.get("scope") or {}
    return scope.get("project_id", "") if isinstance(scope, dict) else ""


def _print_acquired(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    document_claim = claim.get("document_claim") or {}
    print(
        f"acquired steering claim {claim.get('id', '')}: "
        f"project={_project_id(claim)} "
        f"doc={document_claim.get('strategy_doc_slug', '')} "
        f"holder={claim.get('session_id', '')}",
        file=stdout,
    )
    _print_message_handoff(claim, stdout)


def _print_message_handoff(claim: Dict[str, Any], stdout) -> None:
    """Show the exact settled/unacknowledged handoff result."""
    handoff = claim.get("message_handoff") or {}
    drained = int(handoff.get("drained_count") or 0)
    print(
        f"inherited {drained} steering message(s): "
        f"{int(handoff.get('parked_count') or 0)} parked, "
        f"{int(handoff.get('stranded_count') or 0)} unacknowledged from an ended seat",
        file=stdout,
    )
    digest = str(handoff.get("digest") or "")
    if digest:
        print(digest, file=stdout)


def _print_released(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    document_claim = claim.get("document_claim") or {}
    print(
        f"released steering claim {claim.get('id', '')}: "
        f"project={_project_id(claim)} "
        f"doc={document_claim.get('slug', '')} "
        f"holder={claim.get('session_id', '')}",
        file=stdout,
    )


def _print_claims(response: Any, stdout, _stderr) -> None:
    claims = (response.result or {}).get("claims") or []
    if not claims:
        print("no steering claims", file=stdout)
        return
    print("claim_id\tproject\tholder\tstate\tclaimed_at", file=stdout)
    for claim in claims:
        print(
            f"{claim.get('id', '')}\t"
            f"{_project_id(claim)}\t"
            f"{claim.get('session_id', '')}\t"
            f"{'released' if claim.get('released_at') else 'active'}\t"
            f"{claim.get('claimed_at', '')}",
            file=stdout,
        )


def claims_steering_acquire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering acquire",
        description=STEERING_ACQUIRE_USAGE,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument(
        "--doc",
        default=DEFAULT_STEERING_DOC_SLUG,
        help=f"Strategy document to pair (default: {DEFAULT_STEERING_DOC_SLUG}).",
    )
    parser.add_argument("--reason", default=None, help="Optional acquire rationale.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_ACQUIRE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"doc_slug": parsed.doc}
    if parsed.reason:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="claims.steering.acquire",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_acquired,
    )


def claims_steering_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering release",
        description=STEERING_RELEASE_USAGE,
    )
    parser.add_argument("claim_id", help="Steering work_claims.id.")
    parser.add_argument("--reason", required=True, help="Release rationale.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_RELEASE_USAGE)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError:
        return usage_error("CLAIM_ID must be an integer")
    return dispatch_and_emit(
        function_id="claims.steering.release",
        target=TargetRef(kind="claim", claim_id=claim_id),
        payload={"reason": parsed.reason},
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_released,
    )


def claims_steering_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering list",
        description=STEERING_LIST_USAGE,
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument("--session-id", default=None, help="Filter by claim holder.")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Restrict to claims that have not been released.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.session_id:
        payload["session_id"] = parsed.session_id
    if parsed.active_only:
        payload["active_only"] = True
    return dispatch_and_emit(
        function_id="claims.steering.list",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_claims,
    )


USAGE_BY_FUNCTION_ID = {
    "claims.steering.acquire": STEERING_ACQUIRE_USAGE,
    "claims.steering.release": STEERING_RELEASE_USAGE,
    "claims.steering.list": STEERING_LIST_USAGE,
}


__all__ = [
    "STEERING_ACQUIRE_USAGE",
    "STEERING_LIST_USAGE",
    "STEERING_RELEASE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_steering_acquire",
    "claims_steering_list",
    "claims_steering_release",
]
