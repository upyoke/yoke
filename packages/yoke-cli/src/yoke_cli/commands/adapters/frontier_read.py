"""``yoke frontier list`` adapter (read-only frontier projection).

Dispatches the ``frontier.list`` function id: the ranked ready rows and
the gate-labelled blocked rows, computed without writing any telemetry
event rows (the read is poll-safe by construction).
"""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


FRONTIER_LIST_USAGE = (
    "yoke frontier list [--project P] [--wip-cap N] [--full] [--session-id S] [--json]"
)


def _cells(row: Dict[str, Any], fields: List[str]) -> str:
    return "|".join(
        "" if row.get(field) is None else str(row.get(field)) for field in fields
    )


def frontier_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke frontier list",
        usage=FRONTIER_LIST_USAGE,
        description=(
            "List the items ready to start, best first, and the items that\n"
            "wait, each with the gate that holds it. Changes nothing."
        ),
    )
    parser.add_argument(
        "--project", default=None, metavar="P", help="Project to list the frontier for."
    )
    parser.add_argument(
        "--wip-cap",
        type=int,
        default=None,
        metavar="N",
        help="Most items in progress at once; default: project policy.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, FRONTIER_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    payload: Dict[str, Any] = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    if parsed.wip_cap is not None:
        payload["wip_cap"] = parsed.wip_cap
    return dispatch_and_emit(
        function_id="frontier.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["FRONTIER_LIST_USAGE", "frontier_list"]
