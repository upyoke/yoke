"""CLI reads for the unified Items roster and workflow-aware detail."""

from __future__ import annotations

import argparse
from yoke_cli.transport.human_values import write_human
from typing import List

from yoke_cli.commands.adapters.workflow_execution_instructions import (
    render_execution_instruction_block,
    render_item_instruction_summary,
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
from yoke_contracts.item_content_sections import (
    DEFAULT_DETAIL_SECTIONS,
    DETAIL_INCLUDE_SECTIONS,
)


ITEMS_OVERVIEW_LIST_USAGE = (
    "yoke items overview list [--project P] [--projects P,Q] [--limit N] "
    "[--relevance overview] [--search TEXT] [--workflow W] [--status S] "
    "[--page-size N] [--cursor C] [--sort-column C] [--sort-direction D] [--json]"
)
ITEMS_OVERVIEW_LIST_DESCRIPTION = (
    "List workflow-aware item rows for the unified roster. Naming any of "
    "--projects, --search, --workflow, --status, --page-size, --sort-column, --sort-direction, or --cursor "
    "selects the paged roster read, which requires --page-size and returns "
    "match_count plus next_cursor; naming none of them keeps the unpaged "
    "shape. --relevance overview reads the Overview relevance window and "
    "cannot be combined with the paged inputs."
)
ITEMS_DETAIL_GET_USAGE = (
    "yoke items detail get ITEM [--project P] "
    "[--include narrative,body,progress_log] [--full] [--json]"
)
ITEMS_DETAIL_GET_DESCRIPTION = (
    "Read compact item status, workflow and lane facts. Name content sections "
    "with --include, or --full for all fields and operator instruction prose. "
    "JSON returns the response envelope or a saved-response pointer when large."
)


#: ``ItemsOverviewListRequest`` fields this adapter forwards verbatim,
#: paired with the flag that names each one. Range, enum, and cursor
#: validation stay with that model: forwarding what the operator named
#: keeps the CLI from restating the contract's bounds in a second place,
#: and the read already answers an invalid combination with a named
#: refusal and the recovery step.
_OVERVIEW_STRING_FIELDS = (
    "project",
    "relevance",
    "search",
    "workflow",
    "status",
    "cursor",
    "sort_column",
    "sort_direction",
)
_OVERVIEW_INT_FIELDS = ("limit", "page_size")


def items_overview_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items overview list",
        description=ITEMS_OVERVIEW_LIST_DESCRIPTION,
    )
    parser.add_argument(
        "--project",
        help="Single project slug or ref to scope the read to.",
    )
    parser.add_argument(
        "--projects",
        help=(
            "Comma-separated project slugs or refs (paged read). Use "
            "instead of --project to scope one page to several projects."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Cap on rows for the unpaged read.",
    )
    parser.add_argument(
        "--relevance",
        help=(
            "Pass 'overview' to read the Overview relevance window instead "
            "of full history."
        ),
    )
    parser.add_argument(
        "--search",
        help="Free-text roster search (paged read).",
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
    parser.add_argument("--sort-column", help="Roster column to sort (paged read).")
    parser.add_argument("--sort-direction", help="asc or desc (paged read).")
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
        description=ITEMS_DETAIL_GET_DESCRIPTION,
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument(
        "--include",
        help=(
            "Comma-separated content sections to serve in full: "
            f"{', '.join(DETAIL_INCLUDE_SECTIONS)}. Replaces the default "
            f"({', '.join(DEFAULT_DETAIL_SECTIONS)}) rather than adding to "
            "it; pass an empty value for the index alone."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Serve every content section, whatever --include names.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_DETAIL_GET_USAGE)
    if parsed is None:
        return 2
    if parsed.full:
        include = list(DETAIL_INCLUDE_SECTIONS)
    elif parsed.include is None:
        include = list(DEFAULT_DETAIL_SECTIONS)
    else:
        include = split_comma(parsed.include)

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = dict(response.result or {})
        # The operator block renders the instruction prose above the item, so
        # carrying the same text inside the printed result would send it
        # twice. The content index still names the count and the read.
        instructions = result.pop("execution_instructions", None) or []
        stdout.write(
            render_execution_instruction_block(instructions)
            if parsed.full
            else render_item_instruction_summary(instructions, parsed.item)
        )
        if not parsed.full:
            item = result.get("item") or {}
            result = {
                "item": {
                    key: item[key]
                    for key in (
                        "public_ref",
                        "title",
                        "status",
                        "priority",
                        "workflow",
                        "claim",
                        "worktrees",
                        "blocked",
                        "blocked_reason",
                    )
                    if key in item
                },
                "read": f"yoke items detail get {parsed.item} --full",
            }
            workflow = item.get("workflow") or {}
            result["item"]["workflow"] = {
                key: workflow[key]
                for key in ("id", "version", "stage_id", "next_skill_id")
                if key in workflow
            }
            if parsed.include is not None:
                result["content"] = {
                    key: item[key]
                    for key in ("narrative", "body", "progress_log", "content_index")
                    if key in item
                }
        write_human(result, stdout)
        return None

    return dispatch_and_emit(
        function_id="items.detail.get",
        target=item_target("item", parsed.item, parsed.project),
        payload={"include": include},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


USAGE_BY_FUNCTION_ID = {
    "items.overview.list": ITEMS_OVERVIEW_LIST_USAGE,
    "items.detail.get": ITEMS_DETAIL_GET_USAGE,
}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "items_detail_get",
    "items_overview_list",
]
