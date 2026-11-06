"""Apply a unified database claim amendment."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file


__all__ = [
    "db_claim_amend",
    "DB_CLAIM_AMEND_USAGE",
]


DB_CLAIM_AMEND_USAGE = (
    "yoke db-claim amend <PREFIX-N> --reason TEXT "
    "(--payload JSON | --payload-file PATH | --stdin | --state none) "
    "[--project P] [--session-id S] [--json]"
)


def db_claim_amend(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db-claim amend",
        usage=DB_CLAIM_AMEND_USAGE,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="Item id.")
    parser.add_argument(
        "--reason",
        required=True,
        metavar="TEXT",
        help="Why the claim changes; must not be empty.",
    )
    payload_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        payload_group,
        "--payload",
        "--payload-file",
        dest="payload",
        help_text="The new database change claim, as a JSON object.",
        file_help="Read the new claim's JSON from a file.",
    )
    payload_group.add_argument(
        "--stdin",
        action="store_true",
        help="Read the new claim's JSON from stdin.",
    )
    payload_group.add_argument(
        "--state",
        choices=("none",),
        default=None,
        help='No governed migration, including a schema-only additive change; '
        'same as --payload \'{"state":"none"}\'.',
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DB_CLAIM_AMEND_USAGE)
    if parsed is None:
        return 2

    if parsed.state is not None:
        claim: Dict[str, Any] = {"state": parsed.state}
    else:
        try:
            if parsed.stdin:
                raw = sys.stdin.read()
            else:
                raw = resolve_text_file(
                    parsed.payload,
                    parsed.payload_file,
                    "--payload-file",
                )
        except ValueError as exc:
            return usage_error(str(exc))
        try:
            claim = json.loads(raw)
        except json.JSONDecodeError as exc:
            return usage_error(f"claim payload is not valid JSON: {exc}")
        if not isinstance(claim, dict):
            return usage_error("claim payload must be a JSON object")

    payload: Dict[str, Any] = {"claim": claim, "reason": parsed.reason}
    return dispatch_and_emit(
        function_id="db_claim.amend",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
