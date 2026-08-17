"""``yoke overview ...`` flag adapters."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


OVERVIEW_ACTIVATION_GET_USAGE = (
    "yoke overview activation get [--machine-connected] [--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID = {
    "overview.activation.get": OVERVIEW_ACTIVATION_GET_USAGE,
}


def overview_activation_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke overview activation get",
        description=OVERVIEW_ACTIVATION_GET_USAGE,
    )
    parser.add_argument(
        "--machine-connected",
        action="store_true",
        help="Forward host_facts.machine_connected=true to the read.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OVERVIEW_ACTIVATION_GET_USAGE)
    if parsed is None:
        return 2
    payload = {}
    if parsed.machine_connected:
        payload["host_facts"] = {"machine_connected": True}
    return dispatch_and_emit(
        function_id="overview.activation.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "OVERVIEW_ACTIVATION_GET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "overview_activation_get",
]
