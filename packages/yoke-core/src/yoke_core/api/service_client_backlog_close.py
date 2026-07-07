"""Item close command handler for the service_client CLI surface.

Owns ``execute-close`` — the structured-close path that validates, cancels,
regenerates the rendered body, and closes/comments the GitHub issue.
"""

from __future__ import annotations

import io
import sys

from yoke_core.api.service_client_shared import (
    _emit_backlog_result,
    _isolated_test_mutation_error,
    _parse_item_id_arg,
)


def cmd_execute_close(args: list[str]) -> int:
    """Full structured close: validate -> cancel -> md regen -> GitHub close/comment."""
    from yoke_core.domain import backlog

    isolation_error = _isolated_test_mutation_error()
    if isolation_error:
        return _emit_backlog_result({"success": False, "error": isolation_error})

    if not args:
        print("Usage: execute-close <item-id> --reason REASON [--ref REF] [--comment TEXT]", file=sys.stderr)
        return 2

    try:
        item_id = _parse_item_id_arg(args[0])
    except ValueError:
        return _emit_backlog_result(
            {
                "success": False,
                "error": f"Item ID must be integer or YOK-N ref, got '{args[0]}'",
            }
        )

    reason = None
    resolution_ref = None
    resolution_comment = None

    i = 1
    while i < len(args):
        if args[i] == "--reason" and i + 1 < len(args):
            reason = args[i + 1]
            i += 2
        elif args[i] == "--ref" and i + 1 < len(args):
            resolution_ref = args[i + 1]
            i += 2
        elif args[i] == "--comment" and i + 1 < len(args):
            resolution_comment = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if reason is None:
        return _emit_backlog_result(
            {
                "success": False,
                "error": "--reason is required (duplicate, wontfix, obsolete, out-of-scope)",
            }
        )

    captured = io.StringIO()
    result = backlog.execute_close(
        item_id=item_id,
        reason=reason,
        resolution_ref=resolution_ref,
        resolution_comment=resolution_comment,
        rebuild_board=True,
        out=captured,
    )
    return _emit_backlog_result(dict(result), log=captured.getvalue())


__all__ = [
    "cmd_execute_close",
]
