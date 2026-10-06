"""Read path-claim conflicts by integration target or public item ref."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


PATH_CLAIMS_CONFLICTS_LIST_USAGE = (
    "yoke path-claims conflicts list [--integration-target NAME] "
    "[--item PREFIX-N] [--project P] [--session-id S] [--json]"
)


def path_claims_conflicts_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke path-claims conflicts list",
        description=PATH_CLAIMS_CONFLICTS_LIST_USAGE,
    )
    parser.add_argument(
        "--integration-target",
        dest="integration_target",
        default=None,
        help="Filter to a specific integration target (e.g. 'main').",
    )
    parser.add_argument(
        "--item",
        default=None,
        help="Optional item filter (PREFIX-N).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PATH_CLAIMS_CONFLICTS_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.integration_target:
        payload["integration_target"] = parsed.integration_target
    if parsed.item:
        target = item_target("item", parsed.item, parsed.project)
    else:
        target = TargetRef(
            kind="global", project_id=client_project_context(parsed.project)
        )
    return dispatch_and_emit(
        function_id="path_claims.conflicts.list",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
