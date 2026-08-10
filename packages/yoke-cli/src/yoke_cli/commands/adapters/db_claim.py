"""``yoke db-claim …`` flag adapters.

Covers:

- ``db_claim.amend`` — apply a unified DB-claim amendment atomically.
- ``db_claim.prose_check`` — prose-vs-claim detector. Two modes:
  ``PREFIX-N`` relays ``db_claim.prose_check`` (reads stored prose + claim);
  ``--stdin`` runs the detector locally over prose from stdin (no DB;
  works on https before the function is deployed).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

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
    "db_claim_prose_check",
    "DB_CLAIM_AMEND_USAGE",
    "DB_CLAIM_PROSE_CHECK_USAGE",
]


DB_CLAIM_AMEND_USAGE = (
    "yoke db-claim amend <PREFIX-N> --reason TEXT "
    "(--payload JSON | --payload-file PATH | --stdin | --state none) "
    "[--session-id S] [--json]"
)
DB_CLAIM_PROSE_CHECK_USAGE = (
    "yoke db-claim prose-check (<PREFIX-N> | --stdin) "
    "[--item-ref PREFIX-N] [--session-id S] [--json]"
)


def db_claim_amend(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db-claim amend", description=DB_CLAIM_AMEND_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument(
        "--reason", required=True,
        help="Non-empty operator-facing justification.",
    )
    payload_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        payload_group, "--payload", "--payload-file", dest="payload",
        help_text="Unified claim JSON (object). Use --payload-file for a path.",
    )
    payload_group.add_argument(
        "--stdin", action="store_true",
        help="Read unified claim JSON from stdin.",
    )
    payload_group.add_argument(
        "--state", choices=("none",), default=None,
        help='Convenience alias for --payload \'{"state":"none"}\'.',
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
                    parsed.payload, parsed.payload_file, "--payload-file",
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


def db_claim_prose_check(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db-claim prose-check",
        description=DB_CLAIM_PROSE_CHECK_USAGE,
    )
    parser.add_argument(
        "item",
        nargs="?",
        default=None,
        help="Item id (PREFIX-N). Omit when using --stdin.",
    )
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Detect over prose from stdin (local; no DB).",
    )
    parser.add_argument(
        "--item-ref",
        default=None,
        help="Public ref quoted in recovery when using --stdin.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DB_CLAIM_PROSE_CHECK_USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        if parsed.item is not None:
            return usage_error(
                "pass either PREFIX-N or --stdin, not both"
            )
        return _prose_check_stdin(
            item_ref=parsed.item_ref,
            json_mode=parsed.json_mode,
        )
    if not parsed.item:
        return usage_error("PREFIX-N is required unless --stdin is set")
    return dispatch_and_emit(
        function_id="db_claim.prose_check",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _prose_check_stdin(
    *,
    item_ref: Optional[str],
    json_mode: bool,
) -> int:
    """Local detector over stdin prose — https-safe, no control-plane DB."""
    import importlib

    check = importlib.import_module(
        "yoke_core.domain.db_claim_prose_check"
    ).check

    prose = sys.stdin.read()
    outcome = check(prose, profile_raw=None, item_ref=item_ref)
    payload = {
        "blocks": bool(outcome.blocks),
        "triggers": list(outcome.triggers),
        "has_declared_claim": bool(outcome.has_declared_claim),
        "negative_claim_detected": bool(outcome.negative_claim_detected),
        "reviewed_negative_claim_detected": bool(
            outcome.reviewed_negative_claim_detected
        ),
        "matched_snippets": list(outcome.matched_snippets),
        "recovery": outcome.recovery,
        "mode": "stdin",
    }
    if json_mode:
        print(json.dumps({"success": True, "result": payload}, sort_keys=True))
    else:
        print(json.dumps(payload, sort_keys=True))
    return 0
