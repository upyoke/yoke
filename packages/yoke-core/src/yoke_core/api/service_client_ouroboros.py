"""Service-client command for the ouroboros field-note channel.

Wires ``field-note-log`` to :func:`ouroboros_field_note.handle_append`
via :func:`yoke_core.domain.yoke_function_dispatch.dispatch`. The
canonical agent surface is ``yoke ouroboros field-note append``; this
operator-debug fallback exposes the same semantic command.

Usage::

    field-note-log --kind failed      --evidence "recipe R-OP-04 paste blew up: ..."
    field-note-log --kind new         --evidence-file /tmp/missing-recipe.md
    field-note-log --kind unclear     --evidence "purpose unclear for ..." \\
                                      --correlation-id polish-run-2025-05-20
    field-note-log --kind observation --evidence "minor bug not worth a ticket: ..."

``--kind`` is one of ``failed`` (a recipe ran and produced the wrong
result), ``new`` (an agent needed a recipe that did not exist),
``unclear`` (a recipe was present but its purpose was unclear), or
``observation`` (a minor bug or signal not worth a full ticket).
"""

from __future__ import annotations

import argparse
import json
import sys

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.domain.handlers.ouroboros_field_note import (
    EVIDENCE_MAX_CHARS,
    FIELD_NOTE_KIND_VALUES,
)


_USAGE = (
    "field-note-log --kind {failed|new|unclear|observation} "
    "(--evidence TEXT | --evidence-file PATH) "
    "[--correlation-id ID] [--session-id S] [--json]"
)


def cmd_field_note_log(args: list[str]) -> int:
    """Record one agent-authored field-note signal.

    Builds an ``ouroboros.field_note.append`` function call envelope
    and dispatches it through the typed registry. Prints a JSON summary
    on stdout on success; ``--json`` returns the full
    ``FunctionCallResponse`` envelope verbatim.

    Exit codes: 0 on success, 1 on dispatch failure, 2 on CLI usage error.
    """
    parser = argparse.ArgumentParser(prog="field-note-log", add_help=False)
    parser.add_argument(
        "--kind",
        required=True,
        choices=FIELD_NOTE_KIND_VALUES,
        help="Field-note signal — failed, new, unclear, or observation.",
    )
    evidence_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        evidence_group,
        "--evidence",
        "--evidence-file",
        dest="evidence",
        help_text=(
            f"Non-empty evidence text (≤{EVIDENCE_MAX_CHARS} chars). "
            f"Use --evidence-file to read from a path."
        ),
    )
    parser.add_argument(
        "--correlation-id",
        dest="correlation_id",
        default=None,
        help="Optional correlation id (e.g. polish-run id, doctor-run id).",
    )
    parser.add_argument(
        "--session-id",
        default=None,
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
        print(f"Usage: {_USAGE}", file=sys.stderr)
        return 2

    try:
        evidence = resolve_text_file(
            parsed.evidence, parsed.evidence_file, "--evidence-file",
        )
    except ValueError as exc:
        print(
            json.dumps({"success": False, "code": "USAGE", "message": str(exc)}),
            file=sys.stderr,
        )
        return 2

    if not evidence or not evidence.strip():
        print(
            json.dumps({
                "success": False, "code": "USAGE",
                "message": "--evidence must be non-empty",
            }),
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import (
        build_actor,
        call_dispatcher,
        emit_response,
    )

    register_all_handlers()
    actor = build_actor(session_id=parsed.session_id)
    payload = {"kind": parsed.kind, "evidence": evidence}
    if parsed.correlation_id:
        payload["correlation_id"] = parsed.correlation_id

    response = call_dispatcher(
        function_id="ouroboros.field_note.append",
        target=TargetRef(kind="global"),
        payload=payload,
        actor=actor,
    )

    if parsed.json_mode:
        return emit_response(response, json_mode=True)

    if response.success:
        result = response.result or {}
        print(json.dumps({
            "success": True,
            "event_id": result.get("event_id"),
            "kind": result.get("kind"),
            "evidence_preview": result.get("evidence_preview"),
            "correlation_id": result.get("correlation_id"),
        }))
        return 0

    err = response.error
    print(
        json.dumps({
            "success": False,
            "code": (err.code if err is not None else "VALIDATION").upper(),
            "message": err.message if err is not None else "field note emit failed",
        }),
        file=sys.stderr,
    )
    return 1


OUROBOROS_COMMANDS = {
    "field-note-log": cmd_field_note_log,
}


__all__ = ["OUROBOROS_COMMANDS", "cmd_field_note_log"]
