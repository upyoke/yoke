"""``yoke inbox`` and ``yoke decision-requests`` product adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


INBOX_LIST_USAGE = (
    "yoke inbox list [--project-id N ...] [--include-read] [--session-id S] [--json]"
)
DECISION_REQUESTS_RESOLVE_USAGE = (
    "yoke decision-requests resolve REQUEST_ID ACTION [--note TEXT] "
    "[--session-id S] [--json] "
    "(records one decision; an every-approver request stays pending until "
    "every checked role or person has decided)"
)
DECISION_REQUESTS_DISPOSE_ENDED_USAGE = (
    "yoke decision-requests dispose-ended [--project-id N ...] "
    "[--session-id S] [--json]"
)

USAGE_BY_FUNCTION_ID = {
    "inbox.list": INBOX_LIST_USAGE,
    "decision_requests.resolve": DECISION_REQUESTS_RESOLVE_USAGE,
    "decision_requests.dispose_ended": DECISION_REQUESTS_DISPOSE_ENDED_USAGE,
}


def inbox_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke inbox list",
        description=(
            "List the current actor's decision requests and notifications. "
            "Repeat --project-id to restrict the inbox to specific projects; "
            "read notifications are omitted unless --include-read is set."
        ),
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=int,
        default=None,
        help="Project id to include; repeat for more than one project.",
    )
    parser.add_argument(
        "--include-read",
        action="store_true",
        help="Include notifications the current actor has already read.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, INBOX_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project_id:
        payload["project_ids"] = parsed.project_id
    if parsed.include_read:
        payload["include_read"] = True
    return dispatch_and_emit(
        function_id="inbox.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def decision_requests_resolve(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke decision-requests resolve",
        description=(
            "Record your decision on one pending decision request, using an "
            "action that request offers. The server re-evaluates live actor "
            "authority and validates the action against the request kind. "
            "Your decision resolves the request only when the recorded "
            "decisions satisfy its approval policy: under mode 'any' the "
            "first approval settles it, under mode 'all' every checked role "
            "or named person needs its own decision, and any rejection by a "
            "listed party resolves it against. Read approval_progress in the "
            "response for what the gate is still waiting on. A decision is "
            "final: the same actor cannot decide the same request twice."
        ),
    )
    parser.add_argument("request_id", type=int, help="Decision request id.")
    parser.add_argument(
        "action",
        help="Action offered by the request, such as approve, reject, or waive.",
    )
    parser.add_argument(
        "--note",
        default=None,
        help="Optional resolution note; required by actions that request changes.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DECISION_REQUESTS_RESOLVE_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "request_id": parsed.request_id,
        "action": parsed.action,
    }
    if parsed.note is not None:
        payload["note"] = parsed.note
    return dispatch_and_emit(
        function_id="decision_requests.resolve",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def decision_requests_dispose_ended(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke decision-requests dispose-ended",
        description=(
            "Converge pending decision requests whose subjects have already "
            "ended. QA plan executions that stopped reporting progress are "
            "abandoned first, then every pending request whose typed subject "
            "verifiably ended is withdrawn with that end recorded as evidence. "
            "A request whose subject is still live is retained untouched. The "
            "same convergence runs whenever the Inbox is read; this command is "
            "the deliberate operator-run form that returns a receipt."
        ),
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=int,
        default=None,
        help="Project id to converge; repeat for more than one project.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DECISION_REQUESTS_DISPOSE_ENDED_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project_id:
        payload["project_ids"] = parsed.project_id
    return dispatch_and_emit(
        function_id="decision_requests.dispose_ended",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "DECISION_REQUESTS_DISPOSE_ENDED_USAGE",
    "DECISION_REQUESTS_RESOLVE_USAGE",
    "INBOX_LIST_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "decision_requests_dispose_ended",
    "decision_requests_resolve",
    "inbox_list",
]
