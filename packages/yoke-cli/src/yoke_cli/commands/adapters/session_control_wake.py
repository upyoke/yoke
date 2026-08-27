"""Thin CLI adapter for one explicit native session wake."""

from __future__ import annotations

import argparse
import json
from typing import Any, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import write_summary
from yoke_contracts.api.function_call import TargetRef


SESSION_WAKE_USAGE = (
    "yoke session-control session wake (SESSION-ID | --item ITEM) "
    "[--prompt TEXT] [--idempotency-key KEY] [--json]"
)


def _write_wake_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    attempt = result.get("attempt") or {}
    evidence = result.get("evidence") or {}
    write_summary(
        "SESSION WAKE",
        (
            ("SESSION", result.get("target_session_id")),
            ("LIVENESS", result.get("target_liveness")),
            ("MESSAGE", result.get("message_id")),
            ("ATTEMPT", attempt.get("attempt_id") or "queued"),
            ("RESULT", result.get("result_code")),
            ("DEDUPLICATED", bool(result.get("deduplicated"))),
            ("WAKE COUNT", result.get("wake_attempt_count", 0)),
            ("LAST WAKE", result.get("last_wake_at")),
            ("EVIDENCE", json.dumps(evidence, sort_keys=True)),
            ("RECOVERY", result.get("recovery")),
        ),
        stdout,
    )


def session_wake(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control session wake",
        usage=SESSION_WAKE_USAGE,
        description=(
            "Request one stopped-session native resume through the ordinary "
            "message relay, regardless of the target's liveness label."
        ),
    )
    parser.add_argument("target_session_id", metavar="SESSION-ID", nargs="?")
    parser.add_argument(
        "--item",
        default=None,
        help="Wake the item's current work-claim holder.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help=(
            "Prompt delivered by the pending-message envelope; defaults to the "
            "standard pending-message resume prompt."
        ),
    )
    parser.add_argument(
        "--idempotency-key",
        default=None,
        help="Return the same wake receipt when this caller retries the same intent.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_WAKE_USAGE)
    if parsed is None:
        return 2
    if bool(parsed.target_session_id) == bool(parsed.item):
        return usage_error("session wake requires exactly one SESSION-ID or --item")
    payload = (
        {"session_id": parsed.target_session_id}
        if parsed.target_session_id
        else {"item_ref": parsed.item}
    )
    if parsed.prompt:
        payload["prompt"] = parsed.prompt
    if parsed.idempotency_key:
        payload["idempotency_key"] = parsed.idempotency_key
    return dispatch_and_emit(
        function_id="session_control.session.wake",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_wake_result,
        sensitive_values=(parsed.prompt,) if parsed.prompt else (),
    )


__all__ = ["SESSION_WAKE_USAGE", "session_wake"]
