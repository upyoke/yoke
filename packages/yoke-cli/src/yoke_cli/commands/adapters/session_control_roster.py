"""Fixed-column human rendering for the enriched ``sessions.list`` roster."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import (
    write_roster_result,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.liveness import LIVENESS_STATES


SESSION_ROSTER_USAGE = (
    "yoke sessions list [--project P] "
    "[--liveness active|stale|ended|terminated] "
    "[--limit N] [--session S] [--json]"
)
SESSION_ROSTER_HELP = """Find registered top-level sessions and their delivery readiness.

Examples:
  yoke sessions list --liveness active
  yoke sessions list --session SESSION-ID

Next: run `yoke say --help` to preview and send a Fleet message."""


def session_control_roster_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions list",
        usage=SESSION_ROSTER_USAGE,
        description=SESSION_ROSTER_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", default=None, help="Project slug or id.")
    parser.add_argument(
        "--liveness",
        choices=LIVENESS_STATES,
        default=None,
        help="Only show sessions in this liveness state.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum rows.")
    parser.add_argument(
        "--session",
        dest="session_filter",
        default=None,
        help="Return the complete roster row for exactly this session.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSION_ROSTER_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        write_roster_result(response.result or {}, stdout)

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
