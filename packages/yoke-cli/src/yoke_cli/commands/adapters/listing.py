"""``yoke items list|search`` + ``yoke shepherd dependency-list`` adapters.

Backlog-wide read ids:

* ``items.list.run`` — filtered item listing with column projection.
* ``items.search.run`` — keyword search over title + structured fields
  (the dedup-search reader).
* ``shepherd.dependency_list.run`` — both-direction dependency rows for
  one item.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "items_list", "items_search", "shepherd_dependency_list",
    "ITEMS_LIST_USAGE", "ITEMS_SEARCH_USAGE",
    "SHEPHERD_DEPENDENCY_LIST_USAGE",
]


ITEMS_LIST_USAGE = (
    "yoke items list [--status S] [--priority P] [--type T] "
    "[--frozen 0|1] [--blocked 0|1] [--project P|all] "
    '[--fields "f1,f2,..."] [--limit N] [--session-id S] [--json]'
)


def _parse_binary_flag(raw: str, flag: str):
    if raw in ("1", "true", "True"):
        return True, None
    if raw in ("0", "false", "False"):
        return False, None
    return None, usage_error(f"{flag} must be 0 or 1")


def items_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items list", description=ITEMS_LIST_USAGE,
    )
    parser.add_argument("--status", default=None, help="Filter by status.")
    parser.add_argument("--priority", default=None, help="Filter by priority.")
    parser.add_argument("--type", default=None, help="Filter by item type.")
    parser.add_argument("--frozen", default=None, help="Filter frozen flag (0|1).")
    parser.add_argument("--blocked", default=None, help="Filter blocked flag (0|1).")
    add_project_arg(parser)
    parser.add_argument(
        "--fields", default=None,
        help=(
            "Comma-separated column projection "
            "(default id,title,status,priority,type,source)."
        ),
    )
    parser.add_argument(
        "--limit", default=None, help="Max rows returned, 1..1000.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    for key in ("status", "priority", "type"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    # Default scope to the checkout's mapped project, matching board scope:
    # an operator in a project checkout sees that project's items, not the
    # global backlog. `--project all` is the explicit global escape; an
    # explicit slug/id pins that project. Without a checkout mapping, the
    # resolver returns None and the list stays global.
    if (parsed.project or "").strip().lower() != "all":
        scope = client_project_context(parsed.project)
        if scope:
            payload["project"] = scope
    for key, flag in (("frozen", "--frozen"), ("blocked", "--blocked")):
        raw = getattr(parsed, key)
        if raw is None:
            continue
        value, error = _parse_binary_flag(raw, flag)
        if error is not None:
            return error
        payload[key] = value
    if parsed.fields:
        payload["fields"] = split_comma(parsed.fields)
    if parsed.limit is not None:
        try:
            payload["limit"] = int(parsed.limit)
        except ValueError:
            return usage_error("--limit must be an integer")
    return dispatch_and_emit(
        function_id="items.list.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


ITEMS_SEARCH_USAGE = (
    "yoke items search KEYWORDS [--project P|all] [--session-id S] [--json]"
)


def items_search(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items search", description=ITEMS_SEARCH_USAGE,
    )
    parser.add_argument(
        "keywords",
        help="Keyword phrase matched against title/spec/design/plan.",
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_SEARCH_USAGE)
    if parsed is None:
        return 2
    if not parsed.keywords.strip():
        return usage_error("KEYWORDS must be non-empty")
    payload: Dict[str, Any] = {"keywords": parsed.keywords}
    # Default scope to the checkout's project (cwd -> machine-config map),
    # mirroring items list; `--project all` searches every project.
    if (parsed.project or "").strip().lower() != "all":
        scope = client_project_context(parsed.project)
        if scope:
            payload["project"] = scope
    return dispatch_and_emit(
        function_id="items.search.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


SHEPHERD_DEPENDENCY_LIST_USAGE = (
    "yoke shepherd dependency-list (PREFIX-N | --item PREFIX-N) "
    "[--session-id S] [--json]"
)


def shepherd_dependency_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd dependency-list",
        description=SHEPHERD_DEPENDENCY_LIST_USAGE,
    )
    parser.add_argument(
        "--item", default=None,
        help="Item id (PREFIX-N or project-local number). Alternative to positional.",
    )
    parser.add_argument(
        "item_positional", nargs="?", default=None,
        help="Item id positional (alternative to --item).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SHEPHERD_DEPENDENCY_LIST_USAGE)
    if parsed is None:
        return 2
    raw_item = parsed.item or parsed.item_positional
    if not raw_item:
        return usage_error(
            "dependency-list requires --item PREFIX-N or a positional item"
        )
    return dispatch_and_emit(
        function_id="shepherd.dependency_list.run",
        target=item_target("item", raw_item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
