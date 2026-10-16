"""CLI adapters for the ``claims.steering.*`` family."""

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


STEERING_ACQUIRE_USAGE = (
    "yoke claims steering acquire --project P [--doc SLUG | --plan-doc SLUG] "
    "[--reason TEXT] [--json]"
)
STEERING_RELEASE_USAGE = "yoke claims steering release CLAIM_ID --reason TEXT [--json]"
STEERING_LIST_USAGE = (
    "yoke claims steering list [--project P] [--session-id S] [--active-only] [--json]"
)
STEERING_VERIFY_USAGE = "yoke claims steering verify --project P [--json]"


def _scope(claim: Dict[str, Any]) -> Dict[str, Any]:
    scope = claim.get("scope") or {}
    return scope if isinstance(scope, dict) else {}


def _project_id(claim: Dict[str, Any]) -> Any:
    return _scope(claim).get("project_id", "")


def _scope_text(claim: Dict[str, Any]) -> str:
    """Render one seat's coverage: a project, or a document inside it."""
    scope = _scope(claim)
    project = scope.get("project_id", "")
    document = scope.get("document")
    return f"{project}/{document}" if document else f"{project} (whole project)"


def _print_acquired(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    document_claim = claim.get("document_claim") or {}
    print(
        f"acquired steering claim {claim.get('id', '')}: "
        f"scope={_scope_text(claim)} "
        f"doc={document_claim.get('strategy_doc_slug', '')} "
        f"holder={claim.get('session_id', '')}",
        file=stdout,
    )
    _print_message_handoff(claim, stdout)


#: Inherited messages listed by id; the rest stay one list command away.
_HANDOFF_LINES = 20


def _print_message_handoff(claim: Dict[str, Any], stdout) -> None:
    """Summarize inherited states; the complete digest stays in JSON."""
    handoff = claim.get("message_handoff") or {}
    drained = int(handoff.get("drained_count") or 0)
    print(
        f"inherited {drained} steering message(s): "
        f"{int(handoff.get('parked_count') or 0)} parked, "
        f"{int(handoff.get('stranded_count') or 0)} unacknowledged from an ended seat",
        file=stdout,
    )
    messages = handoff.get("messages") or []
    for message in messages[:_HANDOFF_LINES]:
        message_id = str(message.get("message_id") or "")
        line = f"  {message_id}  ack: yoke messages acknowledge {message_id}"
        if not message.get("receipt"):
            line += "  (not injectable: this seat did not resolve as its recipient)"
        print(line, file=stdout)
    if len(messages) > _HANDOFF_LINES:
        print(f"  ... {len(messages) - _HANDOFF_LINES} more", file=stdout)
    print("read: yoke messages list --state unacknowledged", file=stdout)


def _print_released(response: Any, stdout, _stderr) -> None:
    claim = (response.result or {}).get("claim") or {}
    document_claim = claim.get("document_claim") or {}
    print(
        f"released steering claim {claim.get('id', '')}: "
        f"scope={_scope_text(claim)} "
        f"doc={document_claim.get('slug', '')} "
        f"holder={claim.get('session_id', '')}",
        file=stdout,
    )


def _print_claims(response: Any, stdout, _stderr) -> None:
    claims = (response.result or {}).get("claims") or []
    if not claims:
        print("no steering claims", file=stdout)
        return
    print(
        "claim_id\tscope\tholder\tmachine\tsession\tstate\tclaimed_at",
        file=stdout,
    )
    for claim in claims:
        print(
            f"{claim.get('id', '')}\t"
            f"{_scope_text(claim)}\t"
            f"{claim.get('holder_actor_label') or ''}\t"
            f"{claim.get('holder_machine') or ''}\t"
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
        default=None,
        help=(
            "Strategy document this seat steers: narrows the seat to that "
            "document's linked items and takes its lock. Omit for a seat "
            "covering the whole project."
        ),
    )
    parser.add_argument(
        "--plan-doc",
        default=None,
        help=(
            "Standing plan this seat reads and writes: takes that "
            "document's lock while the seat still covers the whole "
            "project. Use with a project-wide seat, never beside --doc."
        ),
    )
    parser.add_argument("--reason", default=None, help="Optional acquire rationale.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_ACQUIRE_USAGE)
    if parsed is None:
        return 2
    if parsed.doc and parsed.plan_doc:
        return usage_error(
            "--doc narrows the seat to a document and already locks it; "
            "--plan-doc locks a document while the seat covers the whole "
            "project. Pass one, not both."
        )
    payload: Dict[str, Any] = {}
    if parsed.doc:
        payload["document"] = parsed.doc
    if parsed.plan_doc:
        payload["plan_document"] = parsed.plan_doc
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


def claims_steering_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke claims steering verify",
        description=STEERING_VERIFY_USAGE,
        epilog=(
            "Answers whether this session holds a live steering seat covering "
            "the project, the authority operator-only commands require. "
            "Refuses with steering_seat_required and the acquire command."
        ),
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_VERIFY_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="claims.steering.verify",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload={},
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_verified,
    )


def _print_verified(response: Any, stdout, _stderr) -> None:
    result = response.result or {}
    print(
        f"steering seat {result.get('claim_id', '')} covers project "
        f"{result.get('project_id', '')} for session {result.get('session_id', '')}",
        file=stdout,
    )


USAGE_BY_FUNCTION_ID = {
    "claims.steering.acquire": STEERING_ACQUIRE_USAGE,
    "claims.steering.release": STEERING_RELEASE_USAGE,
    "claims.steering.list": STEERING_LIST_USAGE,
    "claims.steering.verify": STEERING_VERIFY_USAGE,
}


__all__ = [
    "STEERING_ACQUIRE_USAGE",
    "STEERING_LIST_USAGE",
    "STEERING_RELEASE_USAGE",
    "STEERING_VERIFY_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "claims_steering_acquire",
    "claims_steering_list",
    "claims_steering_verify",
    "claims_steering_release",
]
