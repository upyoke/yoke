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
)
from yoke_contracts.api.function_call import TargetRef


ITEMS_OVERVIEW_LIST_USAGE = (
    "yoke items overview list [--project P] [--limit N] [--json]"
)
ITEMS_DETAIL_GET_USAGE = (
    "yoke items detail get ITEM [--project P] [--json]"
)


def items_overview_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items overview list",
        description="List workflow-aware item rows for the unified roster.",
    )
    parser.add_argument("--project")
    parser.add_argument("--limit", type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_OVERVIEW_LIST_USAGE)
    if parsed is None:
        return 2
    payload = {}
    if parsed.project:
        payload["project"] = parsed.project
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
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


USAGE_BY_FUNCTION_ID = {
    "items.overview.list": ITEMS_OVERVIEW_LIST_USAGE,
    "items.detail.get": ITEMS_DETAIL_GET_USAGE,
}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "items_detail_get",
    "items_overview_list",
]
