"""Batch field-update command handlers for the service_client CLI surface.

Owns ``execute-batch-update`` (programmatic) and ``execute-batch-update-cli``
(the public ``backlog-registry batch-update`` shape that bulk-updates one
field across many items in a single transaction).
"""

from __future__ import annotations

import io
import json
import sys

from yoke_core.api.service_client_shared import (
    _emit_backlog_result,
    _isolated_test_mutation_error,
    _parse_item_id_arg,
    _resolve_session_id,
)


def cmd_execute_batch_update(args: list[str]) -> int:
    """Apply one field update across multiple items."""
    from yoke_core.domain import backlog

    if len(args) < 3:
        print("Usage: execute-batch-update <field> <value> <item-id>...", file=sys.stderr)
        return 2

    field = args[0]
    value = args[1]
    item_ids: list[int] = []
    try:
        for raw in args[2:]:
            item_ids.append(_parse_item_id_arg(raw))
    except ValueError as exc:
        print(json.dumps({"success": False, "error": f"Invalid item ID: {exc}"}))
        return 1

    captured = io.StringIO()
    result = backlog.execute_batch_update(
        item_ids=item_ids,
        field=field,
        value=value,
        session_id=_resolve_session_id(None),
        out=captured,
    )
    result = dict(result)
    result["log"] = captured.getvalue()
    print(json.dumps(result))
    return 0 if result.get("success") else 1


def cmd_execute_batch_update_cli(args: list[str]) -> int:
    """Parse the public backlog-registry batch-update CLI shape in Python."""
    from yoke_core.domain import backlog

    isolation_error = _isolated_test_mutation_error()
    if isolation_error:
        return _emit_backlog_result({"success": False, "error": isolation_error})

    if len(args) < 2:
        print("Usage: execute-batch-update-cli <field=value> <item-id>...", file=sys.stderr)
        return 2

    pair = args[0]
    if "=" not in pair:
        print("Usage: execute-batch-update-cli <field=value> <item-id>...", file=sys.stderr)
        return 2
    field, value = pair.split("=", 1)
    if not field:
        print(f"Invalid field in '{pair}'", file=sys.stderr)
        return 2

    no_rebuild = False
    item_ids: list[int] = []
    try:
        for raw in args[1:]:
            if raw == "--no-rebuild":
                no_rebuild = True
                continue
            item_ids.append(_parse_item_id_arg(raw))
    except ValueError as exc:
        return _emit_backlog_result({"success": False, "error": f"Invalid item ID: {exc}"})

    if not item_ids:
        print("Usage: execute-batch-update-cli <field=value> <item-id>...", file=sys.stderr)
        return 2

    captured = io.StringIO()
    result = backlog.execute_batch_update(
        item_ids=item_ids,
        field=field,
        value=value,
        session_id=_resolve_session_id(None),
        rebuild_board=not no_rebuild,
        out=captured,
    )
    return _emit_backlog_result(dict(result), log=captured.getvalue())


__all__ = [
    "cmd_execute_batch_update",
    "cmd_execute_batch_update_cli",
]
