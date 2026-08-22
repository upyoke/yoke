"""Fixed-column human rendering for the enriched ``sessions.list`` roster."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_common import compact_json
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.roster import (
    SESSION_CONTROL_ROSTER_DISPLAY_FIELDS,
)


SESSION_ROSTER_USAGE = (
    "yoke sessions list [--project P] [--liveness active|stale|ended] "
    "[--limit N] [--session S] [--json]"
)


def _cell(field: str, value: Any) -> str:
    if value is None:
        return ""
    if field == "claims":
        return ",".join(str(claim.get("target") or "") for claim in (value or []))
    if isinstance(value, (dict, list, tuple)):
        return compact_json(value)
    return str(value)


def session_control_roster_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions list",
        description=SESSION_ROSTER_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument(
        "--liveness",
        choices=("active", "stale", "ended"),
        default=None,
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--session",
        dest="session_filter",
        default=None,
        help="Return the point liveness projection for exactly this session.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_ROSTER_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        fields = result.get("fields") or []
        if set(SESSION_CONTROL_ROSTER_DISPLAY_FIELDS).issubset(fields):
            fields = SESSION_CONTROL_ROSTER_DISPLAY_FIELDS
        for row in result.get("rows") or []:
            print(
                "|".join(_cell(field, row.get(field)) for field in fields),
                file=stdout,
            )

    payload = {
        key: value
        for key, value in {
            "project": parsed.project,
            "liveness": parsed.liveness,
            "limit": parsed.limit,
            "session_id": parsed.session_filter,
        }.items()
        if value is not None
    }
    return dispatch_and_emit(
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["SESSION_ROSTER_USAGE", "session_control_roster_list"]
