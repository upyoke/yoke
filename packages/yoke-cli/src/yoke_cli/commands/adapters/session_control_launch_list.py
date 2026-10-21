"""CLI adapter for paging a project's session launches."""

from __future__ import annotations

import argparse
from typing import Any, get_args, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_full_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_common import write_launch_result
from yoke_contracts.api.function_call import FunctionError, TargetRef
from yoke_contracts.session_control.models import LaunchState

LAUNCH_LIST_USAGE = (
    "yoke session-control launch list --project P [--state STATE] "
    "[--surface SURFACE] [--machine MACHINE] [--item PREFIX-N] [--limit N] "
    "[--cursor CURSOR] [--full] [--json]"
)


def _item_filter_floor(response: Any, _actor: Any) -> Any:
    """Name the serving floor when a server predating ``--item`` refuses it."""
    error = response.error
    if (
        response.success
        or error is None
        or error.code != "payload_invalid"
        or "item" not in error.message
    ):
        return response
    return response.model_copy(
        update={
            "success": False,
            "result": None,
            "error": FunctionError(
                code="launch_item_filter_unavailable",
                message=(
                    "Serving floor: `launch list --item`. Ask the control-plane "
                    "operator to install a release carrying it; until then run "
                    "`yoke session-control launch list --project P --json` and "
                    "read each launch's session_name prefix."
                ),
            ),
        }
    )


def session_launch_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control launch list",
        description=LAUNCH_LIST_USAGE
        + " The ITEM column is the item an assignment launch staffs, read from "
        "its session name (PREFIX-N: title). Defaults to compact rows; --full "
        "shows placement, model and registered-session columns.",
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--state", choices=get_args(LaunchState), default=None)
    parser.add_argument("--surface", default=None)
    parser.add_argument("--machine", default=None)
    parser.add_argument(
        "--item",
        default=None,
        help="only launches staffing this item (session name starts with PREFIX-N:)",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument(
        "--cursor",
        default=None,
        help="continuation cursor from a previous page's next_cursor",
    )
    add_full_arg(parser, "all launch table columns; get LAUNCH-ID --full for one launch")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LAUNCH_LIST_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {"project": parsed.project, "limit": parsed.limit}
    for name in ("state", "surface", "machine", "item", "cursor"):
        chosen = getattr(parsed, name)
        if chosen:
            payload[name] = chosen
    return dispatch_and_emit(
        function_id="session_control.launch.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_launch_result,
        response_recovery=_item_filter_floor if parsed.item else None,
    )


__all__ = ["LAUNCH_LIST_USAGE", "session_launch_list"]
