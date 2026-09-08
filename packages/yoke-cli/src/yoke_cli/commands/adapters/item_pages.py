"""CLI reads for the unified Items roster and workflow-aware detail."""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_cli.commands.adapters.workflow_execution_instructions import (
    render_execution_instruction_block,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    split_comma,
)
from yoke_contracts.api.function_call import TargetRef


ITEMS_OVERVIEW_LIST_USAGE = (
    "yoke items overview list [--project P] [--projects P,Q] [--limit N] "
    "[--relevance overview] [--search TEXT] [--workflow W] [--status S] "
    "[--page-size N] [--cursor C] [--json]"
)
ITEMS_OVERVIEW_LIST_DESCRIPTION = (
    "List workflow-aware item rows for the unified roster. Naming any of "
    "--projects, --search, --workflow, --status, --page-size, or --cursor "
    "selects the paged roster read, which requires --page-size and returns "
    "match_count plus next_cursor; naming none of them keeps the unpaged "
    "shape. --relevance overview reads the Overview relevance window and "
    "cannot be combined with the paged inputs."
)
ITEMS_DETAIL_GET_USAGE = (
    "yoke items detail get ITEM [--project P] [--json]"
)
ITEMS_PUBLIC_REF_LOOKUP_USAGE = (
    "yoke items public-ref lookup --id N [--id N ...] [--json]"
)


#: ``ItemsOverviewListRequest`` fields this adapter forwards verbatim,
#: paired with the flag that names each one. Range, enum, and cursor
#: validation stay with that model: forwarding what the operator named
#: keeps the CLI from restating the contract's bounds in a second place,
#: and the read already answers an invalid combination with a named
#: refusal and the recovery step.
_OVERVIEW_STRING_FIELDS = (
    "project", "relevance", "search", "workflow", "status", "cursor",
)
_OVERVIEW_INT_FIELDS = ("limit", "page_size")


def items_overview_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items overview list",
        description=ITEMS_OVERVIEW_LIST_DESCRIPTION,
    )
    parser.add_argument(
        "--project", help="Single project slug or ref to scope the read to.",
    )
    parser.add_argument(
        "--projects",
        help=(
            "Comma-separated project slugs or refs (paged read). Use "
            "instead of --project to scope one page to several projects."
        ),
    )
    parser.add_argument(
        "--limit", type=int, help="Cap on rows for the unpaged read.",
    )
    parser.add_argument(
        "--relevance",
        help=(
            "Pass 'overview' to read the Overview relevance window instead "
            "of full history."
        ),
    )
    parser.add_argument(
        "--search", help="Free-text roster search (paged read).",
    )
    parser.add_argument(
        "--workflow",
        help="Filter the page to one workflow id (paged read).",
    )
    parser.add_argument(
        "--status",
        help="Filter the page to one lifecycle status (paged read).",
    )
    parser.add_argument(
        "--page-size",
        dest="page_size",
        type=int,
        help=(
            "Rows per roster page. Required whenever any other paged input "
            "is named; the read names the accepted range when it refuses."
        ),
    )
    parser.add_argument(
        "--cursor",
        help=(
            "Opaque next_cursor from the previous page's response, to read "
            "the following page."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_OVERVIEW_LIST_USAGE)
    if parsed is None:
        return 2
    # Omitted options stay absent from the payload, so the read keeps
    # choosing between its unpaged and paged shapes on the same evidence
    # it used before these flags existed.
    payload = {}
    for field in _OVERVIEW_STRING_FIELDS:
        value = getattr(parsed, field)
        if value:
            payload[field] = value
    for field in _OVERVIEW_INT_FIELDS:
        value = getattr(parsed, field)
        if value is not None:
            payload[field] = value
    if parsed.projects is not None:
        payload["projects"] = split_comma(parsed.projects)
    return dispatch_and_emit(
        function_id="items.overview.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def items_detail_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items detail get",
        description="Read the workflow-aware detail projection for one item.",
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DETAIL_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = response.result or {}
        stdout.write(render_execution_instruction_block(
            result.get("execution_instructions") or []
        ))
        print(json.dumps(result, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="items.detail.get",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def items_public_ref_lookup(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items public-ref lookup",
        description="Resolve internal item ids to public PREFIX-N refs.",
    )
    parser.add_argument(
        "--id",
        dest="item_ids",
        action="append",
        type=int,
        required=True,
        help="Internal items.id (repeatable).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_PUBLIC_REF_LOOKUP_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="items.public_ref.lookup",
        target=TargetRef(kind="global"),
        payload={"item_ids": parsed.item_ids},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    "items.overview.list": ITEMS_OVERVIEW_LIST_USAGE,
    "items.detail.get": ITEMS_DETAIL_GET_USAGE,
    "items.public_ref.lookup": ITEMS_PUBLIC_REF_LOOKUP_USAGE,
}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "items_detail_get",
    "items_overview_list",
    "items_public_ref_lookup",
]
