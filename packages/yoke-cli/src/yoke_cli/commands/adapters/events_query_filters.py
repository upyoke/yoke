"""Shared public-item filters for event query, tail, count and anomalies."""

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


_FILTER_FLAGS = (
    # (flag, dest, payload_key, help). ``--session`` is the row FILTER;
    # its dest stays distinct from add_session_arg's ``--session-id``
    # (caller identity), which owns the ``session_id`` namespace dest.
    ("--event-name", "event_name", "event_name", "Filter by event name."),
    (
        "--session",
        "session_filter",
        "session_id",
        "Filter rows by events.session_id (caller identity stays --session-id).",
    ),
    (
        "--source-type",
        "source_type",
        "source_type",
        "Filter by source type (agent/backend/system/script/hook/skill).",
    ),
    ("--event-kind", "event_kind", "event_kind", "Filter by event kind."),
    ("--agent", "agent", "agent", "Filter by agent name."),
    ("--service", "service", "service", "Filter by service."),
    ("--actor-id", "actor_id", "actor_id", "Filter by numeric actor id."),
    ("--trace-id", "trace_id", "trace_id", "Filter by trace id."),
    ("--tool-use-id", "tool_use_id", "tool_use_id", "Filter by harness tool-use id."),
    ("--turn-id", "turn_id", "turn_id", "Filter by harness turn id."),
    (
        "--hook-event-name",
        "hook_event_name",
        "hook_event_name",
        "Filter by hook event name.",
    ),
    (
        "--min-severity",
        "min_severity",
        "min_severity",
        "Minimum severity (DEBUG/INFO/STATUS/WARN/ERROR/FATAL).",
    ),
    (
        "--since",
        "since",
        "since",
        'Lower time bound — ISO timestamp or relative ("2 hours ago").',
    ),
    ("--until", "until", "until", "Upper time bound — ISO or relative."),
)


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--item",
        default=None,
        help="Filter by public item ref (PREFIX-N).",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Filter by project slug/id.",
    )
    for flag, dest, _key, help_text in _FILTER_FLAGS:
        parser.add_argument(flag, dest=dest, default=None, help=help_text)
    parser.add_argument(
        "--current-episode",
        dest="current_episode",
        action="store_true",
        help="Bound results to the current session episode (requires --session).",
    )


def _filters_payload(parsed: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for _flag, dest, key, _help in _FILTER_FLAGS:
        value = getattr(parsed, dest, None)
        if value is not None and str(value) != "":
            payload[key] = value
    if parsed.project:
        payload["project"] = parsed.project
    else:
        ambient = client_project_context()
        if ambient:
            payload["project"] = ambient
    if parsed.current_episode:
        payload["current_episode"] = True
    return payload


def _filters_target(parsed: argparse.Namespace) -> TargetRef:
    # The --item filter rides the envelope target as a raw ref; the
    # dispatcher resolves it and the handler reads target.item_id.
    if parsed.item is not None:
        return item_target("item", parsed.item, parsed.project)
    return TargetRef(
        kind="global",
        project_id=client_project_context(parsed.project),
    )


def _dispatch_filtered(
    function_id: str,
    prog: str,
    usage: str,
    args: List[str],
    *,
    with_limit: bool,
    default_limit: int = 50,
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    _add_filter_args(parser)
    if with_limit:
        parser.add_argument(
            "--limit",
            default=str(default_limit),
            help=f"Max rows returned, 1..1000 (default {default_limit}).",
        )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if parsed.current_episode and not parsed.session_filter:
        # Client-side mirror of the server's fail-closed contract.
        return usage_error("--current-episode requires --session SESSION_ID")
    payload = _filters_payload(parsed)
    if with_limit:
        try:
            payload["limit"] = int(parsed.limit)
        except ValueError:
            return usage_error("--limit must be an integer")
    return dispatch_and_emit(
        function_id=function_id,
        target=_filters_target(parsed),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
