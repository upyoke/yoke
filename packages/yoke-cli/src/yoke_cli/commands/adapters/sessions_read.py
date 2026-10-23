"""``yoke sessions list`` adapter (read-only session roster).

Split from :mod:`yoke_cli.commands.adapters.sessions` (which owns the
begin / touch / checkpoint / offer wrappers) to keep that module under
the authored-file line cap.
"""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human
from yoke_cli.commands.adapters.session_control_recipient_output import (
    recipient_project,
)

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_full_arg,
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.liveness import ENDED_CAUSES, LIVENESS_STATES


SESSIONS_LIST_USAGE = (
    "yoke sessions list [--project P] [--liveness active|waiting|stale|ended] "
    "[--ended-cause killed|wound_down] "
    "[--limit N] [--offset N] [--full] [--session S] [--session-id S] [--json]"
)

SESSIONS_STEERING_GROUPS_LIST_USAGE = (
    "yoke sessions steering-groups list [--session-id S] [--json]"
)


def _cell(row: Dict[str, Any], field: str) -> str:
    value = row.get(field)
    if field == "claims":
        return ",".join(str(claim.get("target") or "") for claim in (value or []))
    return "" if value is None else str(value)


def sessions_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions list",
        usage=SESSIONS_LIST_USAGE,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Only sessions in this project, excluding outside-project sessions.",
    )
    parser.add_argument(
        "--liveness",
        choices=LIVENESS_STATES,
        default=None,
        help="Only sessions in this liveness state.",
    )
    parser.add_argument(
        "--ended-cause",
        dest="ended_cause",
        choices=ENDED_CAUSES,
        default=None,
        help="Only ended sessions with this cause.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Most rows to show.")
    parser.add_argument(
        "--offset", type=int, default=0, help="Rows to skip first; default: 0."
    )
    add_full_arg(
        parser,
        "all sessions and their diagnostics, holdings, usage and messageability unless --limit is named",
    )
    parser.add_argument(
        "--session",
        default=None,
        dest="session_filter",
        help="Single-session liveness projection for exactly this id "
        "(--session-id remains the caller-identity override).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        displayed = [
            {**row, "project": recipient_project(row)} for row in result.get("rows", [])
        ]
        write_human({**result, "rows": displayed}, stdout)

    payload: Dict[str, Any] = {
        "detail": "full" if parsed.full else "summary",
        "offset": parsed.offset,
    }
    for key in ("project", "liveness", "ended_cause"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    if parsed.session_filter is not None:
        payload["session_id"] = parsed.session_filter
    return dispatch_and_emit(
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def sessions_get(args: List[str]) -> int:
    """Read one session through the roster's exact-session projection."""
    parser = argparse.ArgumentParser(prog="yoke sessions get")
    parser.add_argument("session", help="Session id to read.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, "yoke sessions get SESSION [--json]")
    if parsed is None:
        return 2
    forwarded = ["--session", parsed.session, "--full"]
    if parsed.session_id:
        forwarded.extend(("--session-id", parsed.session_id))
    if parsed.json_mode:
        forwarded.append("--json")
    return sessions_list(forwarded)


def sessions_steering_groups_list(args: List[str]) -> int:
    """Which steering groups are live — the seats, not the sessions in them."""
    parser = argparse.ArgumentParser(
        prog="yoke sessions steering-groups list",
        description=(
            "List the session id of every live steering seat visible to you. "
            "One row per group; the roster carries the same identity as "
            "steering_group_session_id on every session it covers."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_STEERING_GROUPS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="sessions.steering_groups.list",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "SESSIONS_LIST_USAGE",
    "SESSIONS_STEERING_GROUPS_LIST_USAGE",
    "sessions_list",
    "sessions_steering_groups_list",
]
