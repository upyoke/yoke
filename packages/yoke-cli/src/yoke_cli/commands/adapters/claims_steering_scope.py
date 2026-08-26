"""CLI adapters for the ``claims.steering_scope.*`` family."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


STEERING_SCOPE_ACQUIRE_USAGE = (
    "yoke claims steering-scope acquire --project P "
    "[--strategy-doc SLUG ...] [--reason TEXT] [--json]"
)
STEERING_SCOPE_RELEASE_USAGE = (
    "yoke claims steering-scope release CLAIM_ID --reason TEXT [--json]"
)
STEERING_SCOPE_LIST_USAGE = (
    "yoke claims steering-scope list [--project P] [--session-id S] "
    "[--active-only] [--json]"
)


def _scope_label(claim: Dict[str, Any]) -> str:
    slugs = list(claim.get("steering_strategy_doc_slugs") or [])
    return ",".join(slugs) if slugs else "whole-project"


def _print_acquired(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    print(
        f"acquired steering-scope claim {claim.get('id', '')}: "
        f"project={claim.get('steering_project_id', '')} "
        f"scope={_scope_label(claim)} "
        f"holder={claim.get('owner_session_id') or claim.get('session_id') or ''}",
        file=stdout,
    )


def _print_released(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    print(
        f"released steering-scope claim {claim.get('id', '')}: "
        f"project={claim.get('steering_project_id', '')} "
        f"scope={_scope_label(claim)} "
        f"holder={claim.get('owner_session_id') or claim.get('session_id') or ''}",
        file=stdout,
    )


def _print_claims(response: Any, stdout, _stderr) -> None:
    claims = (response.result or {}).get("claims") or []
    if not claims:
        print("no steering-scope claims", file=stdout)
        return
    print("claim_id\tproject\tscope\tholder\tstate\tclaimed_at", file=stdout)
    for claim in claims:
        print(
            f"{claim.get('id', '')}\t"
            f"{claim.get('steering_project_id', '')}\t"
            f"{_scope_label(claim)}\t"
            f"{claim.get('owner_session_id') or claim.get('session_id') or ''}\t"
            f"{'released' if claim.get('released_at') else 'active'}\t"
            f"{claim.get('claimed_at', '')}",
            file=stdout,
        )


def claims_steering_scope_acquire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering-scope acquire",
        description=STEERING_SCOPE_ACQUIRE_USAGE,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument(
        "--strategy-doc",
        dest="strategy_docs",
        action="append",
        default=[],
        help=(
            "Strategy-document slug in the steering scope; repeat for more. "
            "Omit for the whole project."
        ),
    )
    parser.add_argument("--reason", default=None, help="Optional acquire rationale.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_SCOPE_ACQUIRE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "strategy_doc_slugs": list(parsed.strategy_docs),
    }
    if parsed.reason:
        payload["reason"] = parsed.reason
    return dispatch_and_emit(
        function_id="claims.steering_scope.acquire",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload=payload,
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_acquired,
    )


def claims_steering_scope_release(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering-scope release",
        description=STEERING_SCOPE_RELEASE_USAGE,
    )
    parser.add_argument("claim_id", help="Steering-scope work_claims.id.")
    parser.add_argument("--reason", required=True, help="Release rationale.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_SCOPE_RELEASE_USAGE)
    if parsed is None:
        return 2
    try:
        claim_id = int(parsed.claim_id)
    except ValueError:
        return usage_error("CLAIM_ID must be an integer")
    return dispatch_and_emit(
        function_id="claims.steering_scope.release",
        target=TargetRef(kind="claim", claim_id=claim_id),
        payload={"reason": parsed.reason},
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_released,
    )


def claims_steering_scope_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering-scope list",
        description=STEERING_SCOPE_LIST_USAGE,
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument("--session-id", default=None, help="Filter by claim holder.")
    parser.add_argument(
        "--active-only",
        action="store_true",
        help="Restrict to claims that have not been released.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_SCOPE_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.session_id:
        payload["session_id"] = parsed.session_id
    if parsed.active_only:
        payload["active_only"] = True
    return dispatch_and_emit(
        function_id="claims.steering_scope.list",
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
    "claims.steering_scope.acquire": STEERING_SCOPE_ACQUIRE_USAGE,
    "claims.steering_scope.release": STEERING_SCOPE_RELEASE_USAGE,
    "claims.steering_scope.list": STEERING_SCOPE_LIST_USAGE,
}


__all__ = [
    "STEERING_SCOPE_ACQUIRE_USAGE",
    "STEERING_SCOPE_LIST_USAGE",
    "STEERING_SCOPE_RELEASE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_steering_scope_acquire",
    "claims_steering_scope_list",
    "claims_steering_scope_release",
]
