"""``yoke ouroboros entry …`` + ``yoke scratch dispatch-inputs`` adapters.

Covers the function ids whose target shape differs from the items/claims
patterns (the events.* family lives in
:mod:`yoke_cli.commands.adapters.events`, and the field-note channel's own
CLI surface in :mod:`yoke_cli.commands.adapters.ouroboros_field_note`):

* ``ouroboros.entry.list`` / ``ouroboros.entry.get`` — curate-loop
  entry readers (target.kind ``global``)
* ``scratch.dispatch_inputs`` — client-local path resolver
"""

from __future__ import annotations

import argparse
import importlib
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    resolve_item_id_via_dispatch,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "ouroboros_entry_list", "ouroboros_entry_get",
    "scratch_dispatch_inputs",
    "OUROBOROS_ENTRY_LIST_USAGE", "OUROBOROS_ENTRY_GET_USAGE",
    "SCRATCH_DISPATCH_INPUTS_USAGE",
]


# ---------------------------------------------------------------------------
# ouroboros.entry.list / ouroboros.entry.get
# ---------------------------------------------------------------------------

OUROBOROS_ENTRY_LIST_USAGE = (
    "yoke ouroboros entry list [--unreviewed] [--project P] "
    "[--limit N] [--offset N] [--count] [--session-id S] [--json]"
)


def ouroboros_entry_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry list",
        description=OUROBOROS_ENTRY_LIST_USAGE,
    )
    parser.add_argument(
        "--unreviewed", action="store_true",
        help="Only entries not yet reviewed or archived.",
    )
    parser.add_argument(
        "--project", default=None, help="Filter by project slug or id.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum rows to return (default 50, max 500).",
    )
    parser.add_argument(
        "--offset", type=int, default=None,
        help="Rows to skip before the page (default 0).",
    )
    parser.add_argument(
        "--count", action="store_true",
        help="Return the matching row count instead of entry bodies.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_ENTRY_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.unreviewed:
        payload["unreviewed"] = True
    if parsed.project:
        payload["project"] = parsed.project
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    if parsed.offset is not None:
        payload["offset"] = parsed.offset
    if parsed.count:
        payload["count"] = True
    return dispatch_and_emit(
        function_id="ouroboros.entry.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


OUROBOROS_ENTRY_GET_USAGE = (
    "yoke ouroboros entry get ENTRY_ID [--session-id S] [--json]"
)


def ouroboros_entry_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry get",
        description=OUROBOROS_ENTRY_GET_USAGE,
    )
    parser.add_argument("entry_id", help="Ouroboros entry id (integer).")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_ENTRY_GET_USAGE)
    if parsed is None:
        return 2
    try:
        entry_id = int(parsed.entry_id)
    except ValueError:
        return usage_error("ENTRY_ID must be an integer")
    return dispatch_and_emit(
        function_id="ouroboros.entry.get",
        target=TargetRef(kind="global"),
        payload={"entry_id": entry_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# scratch.dispatch_inputs
# ---------------------------------------------------------------------------

SCRATCH_DISPATCH_INPUTS_USAGE = (
    "yoke scratch dispatch-inputs <PREFIX-N|item-id> <session_id> <attempt>"
)


def scratch_dispatch_inputs(args: List[str]) -> int:
    """Print the helper-resolved dispatch-inputs absolute path.

    Resolves the path locally via
    :func:`yoke_core.domain.project_scratch_dir.dispatch_inputs_dir`
    (no HTTP roundtrip — the shepherd skill's ``$(...)`` capture is the
    canonical caller and shell-recipe latency would dominate). The
    grammar-rule function id is ``scratch.dispatch_inputs``; the
    matching CLI tokens are ``("scratch", "dispatch-inputs")``.

    Output contract: exactly one line on stdout, the absolute path,
    terminated by a single ``\\n``. Stderr is reserved for errors.
    """

    import sys

    scratch_dir = importlib.import_module(
        "yoke_core.domain.project_scratch_dir"
    )
    parser = argparse.ArgumentParser(
        prog="yoke scratch dispatch-inputs",
        description=SCRATCH_DISPATCH_INPUTS_USAGE,
    )
    parser.add_argument("item", help="Item id (PREFIX-N or project-local number).")
    parser.add_argument("session_id", help="Harness session id.")
    parser.add_argument("attempt", help="Per-dispatch attempt counter (1-based).")
    parsed = parse_or_usage_error(parser, args, SCRATCH_DISPATCH_INPUTS_USAGE)
    if parsed is None:
        return 2

    try:
        item_id = resolve_item_id_via_dispatch(
            parsed.item, parsed.project, parsed.session_id,
        )
    except ValueError as exc:
        return usage_error(str(exc))
    try:
        attempt = int(parsed.attempt)
    except ValueError:
        return usage_error("attempt must be an integer")
    if attempt < 1:
        return usage_error("attempt must be >= 1")
    if not parsed.session_id.strip():
        return usage_error("session_id must be non-empty")

    project = scratch_dir.resolve_active_project()
    path = scratch_dir.dispatch_inputs_dir(project, item_id, parsed.session_id, attempt)
    sys.stdout.write(f"{path}\n")
    sys.stdout.flush()
    return 0
