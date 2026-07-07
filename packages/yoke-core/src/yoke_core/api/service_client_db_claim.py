"""Service-client command for the unified DB-claim amendment workflow.

Wires ``db-claim-amend`` to :func:`yoke_core.domain.db_claim.amend`.
The CLI is the sanctioned surface operators, agents, and skill prose
use when they need to write or correct a ticket's DB claim — all other
paths (``/yoke idea`` late classification, ``/yoke refine``
stale-claim repair, ``/yoke advance`` / ``/yoke polish`` discovery)
call through this surface rather than mutating the two JSON fields
directly.

Usage::

    db-claim-amend --item YOK-N --state none --reason "no governed DB work"

    db-claim-amend --item YOK-N --payload '{"state":"declared", ...}' \\
                   --reason "declared governed schema change"

    cat claim.json | db-claim-amend --item YOK-N --payload - \\
                                    --reason "from reviewer"

``--state none`` is a convenience for clearing a claim. Any other
amendment supplies the unified payload via ``--payload`` (a JSON string
or ``-`` for stdin).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file


_YOKE_OR_BARE_ID_RE = re.compile(r"^(?:YOK-)?(\d+)$", re.IGNORECASE)


def _parse_item_id(raw: str) -> int:
    """Parse ``YOK-N`` or a bare integer into the numeric item id."""
    if raw is None:
        raise ValueError("item id is required")
    match = _YOKE_OR_BARE_ID_RE.match(raw.strip())
    if not match:
        raise ValueError(
            f"invalid item id {raw!r}; expected 'YOK-N' or a bare integer"
        )
    return int(match.group(1))


def _load_payload(raw: str) -> Dict[str, Any]:
    if raw == "-":
        raw = sys.stdin.read()
    if not raw or not raw.strip():
        raise ValueError("--payload is empty")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"--payload is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(
            "--payload must decode to a JSON object; got "
            f"{type(parsed).__name__}"
        )
    return parsed


def cmd_db_claim_amend(args: list[str]) -> int:
    """Apply a unified DB-claim amendment atomically.

    Routes through the function dispatcher (``db_claim.amend``).

    Prints a JSON summary to stdout on success; a JSON error (with
    ``success: false`` and ``code``) to stderr on failure. Exit 0 on
    success, 1 on validation failure, 2 on CLI usage error.

    ``--json`` mode emits the typed FunctionCallResponse envelope verbatim
    instead of the legacy summary dict.
    """
    parser = argparse.ArgumentParser(
        prog="db-claim-amend", add_help=False
    )
    parser.add_argument(
        "--item", required=True,
        help="Backlog item ref (PREFIX-N).",
    )
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        reason_group, "--reason", "--reason-file", dest="reason",
        help_text="Non-empty operator-facing justification.",
    )
    reason_group.add_argument("--intent", dest="reason")
    payload_group = parser.add_mutually_exclusive_group()
    payload_group.add_argument(
        "--payload", default=None,
        help="Unified claim JSON (object). Pass '-' to read from stdin.",
    )
    payload_group.add_argument(
        "--state",
        choices=("none",),
        default=None,
        help=(
            "Convenience alias for --payload '{\"state\":\"none\"}'. "
            "Only 'none' is accepted here; declared claims require "
            "--payload so the authored fields are explicit."
        ),
    )
    parser.add_argument(
        "--session-id", default=None,
        help="Session id override; defaults to YOKE_SESSION_ID etc.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit the typed FunctionCallResponse envelope verbatim.",
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: db-claim-amend --item YOK-N --reason R "
            "(--payload JSON|- | --state none) [--session-id S] [--json]",
            file=sys.stderr,
        )
        return 2

    if parsed.payload is None and parsed.state is None:
        print(
            json.dumps({
                "success": False,
                "code": "USAGE",
                "message": "one of --payload or --state is required",
            }),
            file=sys.stderr,
        )
        return 2

    try:
        item_id = _parse_item_id(parsed.item)
    except ValueError as exc:
        print(
            json.dumps({
                "success": False,
                "code": "USAGE",
                "message": str(exc),
            }),
            file=sys.stderr,
        )
        return 2

    try:
        reason = resolve_text_file(parsed.reason, parsed.reason_file, "--reason-file")
    except ValueError as exc:
        print(json.dumps({"success": False, "code": "USAGE", "message": str(exc)}), file=sys.stderr)
        return 2

    try:
        if parsed.state is not None:
            payload: Dict[str, Any] = {"state": parsed.state}
        else:
            payload = _load_payload(parsed.payload)
    except ValueError as exc:
        print(
            json.dumps({
                "success": False,
                "code": "USAGE",
                "message": str(exc),
            }),
            file=sys.stderr,
        )
        return 2

    # Route through the function dispatcher (``db_claim.amend``).
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
        emit_response,
    )

    register_all_handlers()
    actor = build_actor(session_id=parsed.session_id)
    response = call_dispatcher(
        function_id="db_claim.amend",
        target=TargetRef(kind="item", item_id=item_id),
        payload={"claim": payload, "reason": reason},
        actor=actor,
    )

    if parsed.json_mode:
        return emit_response(response, json_mode=True)

    if response.success:
        result = response.result or {}
        print(json.dumps({
            "success": True,
            "item_id": result.get("item_id"),
            "previous_profile": result.get("previous_profile", {}),
            "previous_attestation": result.get("previous_attestation", {}),
            "new_profile": result.get("new_profile", {}),
            "new_attestation": result.get("new_attestation", {}),
            "reason": result.get("reason", reason),
            "event_id": result.get("event_id"),
        }))
        return 0

    err = response.error
    print(
        json.dumps({
            "success": False,
            "code": (err.code if err is not None else "VALIDATION").upper(),
            "message": err.message if err is not None else "amend failed",
        }),
        file=sys.stderr,
    )
    return 1


__all__ = ["cmd_db_claim_amend"]
