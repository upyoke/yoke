"""``yoke sessions list`` adapter (read-only session roster).

Split from :mod:`yoke_cli.commands.adapters.sessions` (which owns the
begin / touch / checkpoint / offer wrappers) to keep that module under
the authored-file line cap.
"""

from __future__ import annotations
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list

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
from yoke_contracts.api.function_call import TargetRef, FunctionError
from yoke_contracts.session_control.liveness import ENDED_CAUSES
from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.session_state_fields import (
    SESSION_STATE_CHOICES,
    session_state_columns,
)


SESSIONS_LIST_USAGE = (
    "yoke sessions list [--project P] [--status working|waiting|ended] "
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
        description=(
            "Read Working, Waiting or Ended status, reason and active age. "
            "Filters run before pagination. Example: yoke sessions list --status working. "
            "Next: yoke say --help."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Only sessions in this project, excluding outside-project sessions.",
    )
    for field, choices in SESSION_STATE_CHOICES.items():
        parser.add_argument(
            f"--{field}",
            choices=choices,
            help=f"Filter canonical {field} before pagination.",
        )
    parser.add_argument(
        "--ended-cause",
        dest="ended_cause",
        choices=ENDED_CAUSES,
        default=None,
        help="Only ended sessions with this cause.",
    )
    add_page_args(parser, limit=None)
    add_full_arg(
        parser,
        "all sessions and their diagnostics, holdings, usage and messageability unless --limit is named",
    )
    parser.add_argument(
        "--session",
        default=None,
        dest="session_filter",
        help="Single-session state projection for exactly this id "
        "(--session-id remains the caller-identity override).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_LIST_USAGE)
    if parsed is None:
        return 2

    payload: Dict[str, Any] = {
        "detail": "full" if parsed.full else "summary",
        "offset": parsed.offset,
    }
    for key in ("project", *SESSION_STATE_CHOICES, "ended_cause"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    if parsed.session_filter is not None:
        payload["session_id"] = parsed.session_filter
    return dispatch_list(
        parsed=parsed,
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        response_recovery=validate_session_status,
        human_writer=lambda response, out, err: write_sessions_result(
            response, out, err, full=parsed.full
        ),
    )


def validate_session_status(response, _actor):
    if response.success and (
        not {"status", "active_at", "reason"}.issubset(
            (response.result or {}).get("fields", [])
        )
        or any(
            (row.get("session_state") or {}).get("status")
            not in SESSION_STATE_CHOICES["status"]
            or "active_at" not in (row.get("session_state") or {})
            or not isinstance((row.get("session_state") or {}).get("reason"), str)
            for row in (response.result or {}).get("rows", [])
        )
    ):
        return response.model_copy(
            update={
                "success": False,
                "result": None,
                "error": FunctionError(
                    code="function_version_skew",
                    message=compose_refusal(
                        "Session state unavailable; required server floor next-release",
                        recovery="Refresh after the server upgrade; ask the release operator for the carrying release",
                    ),
                ),
            }
        )
    return response


def write_sessions_result(response, stdout, stderr, *, full=False) -> None:
    result = response.result or {}
    rows = result.get("rows") or []
    if full:
        write_human(
            {
                **result,
                "fields": [
                    field for field in result.get("fields", []) if field != "liveness"
                ],
                "rows": [
                    {key: value for key, value in row.items() if key != "liveness"}
                    for row in rows
                ],
            },
            stdout,
        )
        return

    displayed = []
    for row in rows:
        state = session_state_columns(row)
        holds = state.get("holds") or []
        label = row.get("display_label")
        identity = row.get("session_id")
        displayed.append(
            {
                "session": f"{label} ({identity})" if label else identity,
                "project": recipient_project(row),
                "status": str(state["status"]).capitalize(),
                "reason": state["reason"],
                "active": (
                    f"{max(0, int((utc_now() - parse_instant(state['active_at'])).total_seconds()) // 60)}m ago"
                    if state["active_at"]
                    else "unavailable"
                ),
                "holds": ", ".join(
                    str(
                        h.get("public_ref")
                        or h.get("target")
                        or h.get("kind")
                        or "hold"
                    )
                    for h in holds
                ),
            }
        )
    write_human(
        {
            "rows": displayed,
            **{
                key: result[key]
                for key in ("offset", "limit", "next_offset")
                if key in result
            },
        },
        stdout,
    )
    print("Details: yoke sessions get SESSION; yoke sessions list --full", file=stdout)


def sessions_get(args: List[str]) -> int:
    """Read one session through the roster's exact-session projection."""
    parser = argparse.ArgumentParser(prog="yoke sessions get")
    parser.add_argument("session", help="Session id to read.")
    add_full_arg(parser, "the session diagnostics and detail fields")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, "yoke sessions get SESSION [--full] [--session-id S] [--json]"
    )
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
