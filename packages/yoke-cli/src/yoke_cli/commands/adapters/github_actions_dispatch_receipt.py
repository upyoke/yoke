"""Read a workflow dispatch's durable inputs and run identity."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.github_actions_workflow import (
    _call,
    _emit_operation_error,
)
from yoke_cli.transport.dispatcher import emit_response

GITHUB_ACTIONS_DISPATCH_RECEIPT_USAGE = (
    "yoke github-actions dispatch-receipt get REQUEST-ID "
    "--project P [--session-id S] [--json]"
)


def github_actions_dispatch_receipt_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions dispatch-receipt get",
        description=(
            "Read the original inputs and run for one durable dispatch request. "
            "Use its original inputs when rejoining; a changed payload with "
            "the same request id is refused. Missing records return found=false."
        ),
    )
    parser.add_argument("request_id", help="Id of the dispatch request to read.")
    parser.add_argument(
        "--project", required=True, help="Project that made the dispatch request."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_DISPATCH_RECEIPT_USAGE)
    if parsed is None:
        return 2
    response = _call(
        "github_actions.dispatch_receipt.get",
        {"project": parsed.project, "dispatch_request_id": parsed.request_id},
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    emit_response(response, json_mode=parsed.json_mode)
    return 0
