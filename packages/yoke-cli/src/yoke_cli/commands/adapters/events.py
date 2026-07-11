"""``yoke events {emit,query,tail,count,anomalies}`` adapters.

Read ids over the events ledger share one filter-flag surface
(the payload keys mirror ``yoke_core.domain.handlers.events_reads``):

* ``events.emit`` — write one structured event.
* ``events.query.run`` — filtered rows, newest first.
* ``events.tail.run`` — zero-config recent slice.
* ``events.count.run`` — aggregate count over the same filters.
* ``events.anomalies.run`` — rows whose ``anomaly_flags`` is non-empty.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "events_emit", "events_query", "events_tail", "events_count",
    "events_anomalies",
    "EVENTS_EMIT_USAGE", "EVENTS_QUERY_USAGE", "EVENTS_TAIL_USAGE",
    "EVENTS_COUNT_USAGE", "EVENTS_ANOMALIES_USAGE",
]


EVENTS_EMIT_USAGE = (
    "yoke events emit --name NAME --kind KIND --type TYPE "
    "--source-type SOURCE [--severity LEVEL] [--outcome OUTCOME] "
    "[--project P] [--context JSON] [--session-id S] [--json]"
)


def _add_emit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--type", required=True)
    parser.add_argument("--source-type", required=True)
    parser.add_argument("--severity", default="INFO")
    parser.add_argument("--outcome", default="completed")
    for flag in (
        "org-id", "environment", "request-id", "project",
        "item-id", "agent", "tool-name", "trace-id", "parent-id",
        "anomaly-flags", "tool-use-id", "turn-id", "hook-event-name",
    ):
        parser.add_argument(f"--{flag}", default=None)
    parser.add_argument("--task-num", type=int, default=None)
    parser.add_argument("--duration-ms", type=int, default=None)
    parser.add_argument("--exit-code", type=int, default=None)
    parser.add_argument("--context", default=None)
    parser.add_argument("--error-context", default=None)


def _emit_context(raw_context: str | None, raw_error: str | None) -> Dict[str, Any]:
    context: Dict[str, Any] = {}
    detail = _parse_json_context(raw_context, label="context")
    if detail is not None:
        context["detail"] = detail
    error = _parse_json_context(raw_error, label="error-context")
    if error is not None:
        context["error"] = error
    return context


def _parse_json_context(raw: str | None, *, label: str) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc}") from exc


def events_emit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke events emit",
        description=EVENTS_EMIT_USAGE,
    )
    _add_emit_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EVENTS_EMIT_USAGE)
    if parsed is None:
        return 2
    try:
        context = _emit_context(parsed.context, parsed.error_context)
    except ValueError as exc:
        return usage_error(str(exc))

    payload: Dict[str, Any] = {
        "name": parsed.name,
        "kind": parsed.kind,
        "type": parsed.type,
        "source_type": parsed.source_type,
        "severity": parsed.severity,
        "outcome": parsed.outcome,
        "context": context,
    }
    for attr in (
        "org_id", "environment", "request_id", "project",
        "item_id", "task_num", "agent", "tool_name", "duration_ms",
        "exit_code", "trace_id", "parent_id", "anomaly_flags",
        "tool_use_id", "turn_id", "hook_event_name",
    ):
        value = getattr(parsed, attr)
        if value is not None and str(value) != "":
            payload[attr] = value

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("reason") not in ("", None, "severity_filtered"):
            print(json.dumps(result, sort_keys=True), file=stdout)

    return dispatch_and_emit(
        function_id="events.emit",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


_FILTER_FLAGS = (
    # (flag, dest, payload_key, help). ``--session`` is the row FILTER;
    # its dest stays distinct from add_session_arg's ``--session-id``
    # (caller identity), which owns the ``session_id`` namespace dest.
    ("--event-name", "event_name", "event_name", "Filter by event name."),
    ("--session", "session_filter", "session_id",
     "Filter rows by events.session_id (caller identity stays --session-id)."),
    ("--source-type", "source_type", "source_type",
     "Filter by source type (agent/backend/system/script/hook/skill)."),
    ("--event-kind", "event_kind", "event_kind", "Filter by event kind."),
    ("--agent", "agent", "agent", "Filter by agent name."),
    ("--service", "service", "service", "Filter by service."),
    ("--actor-id", "actor_id", "actor_id", "Filter by numeric actor id."),
    ("--trace-id", "trace_id", "trace_id", "Filter by trace id."),
    ("--tool-use-id", "tool_use_id", "tool_use_id",
     "Filter by harness tool-use id."),
    ("--turn-id", "turn_id", "turn_id", "Filter by harness turn id."),
    ("--hook-event-name", "hook_event_name", "hook_event_name",
     "Filter by hook event name."),
    ("--min-severity", "min_severity", "min_severity",
     "Minimum severity (DEBUG/INFO/STATUS/WARN/ERROR/FATAL)."),
    ("--since", "since", "since",
     'Lower time bound — ISO timestamp or relative ("2 hours ago").'),
    ("--until", "until", "until", "Upper time bound — ISO or relative."),
)


def _add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--item", default=None,
        help="Filter by item id (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--project", default=None,
        help="Filter by project slug/id; doubles as bare item-ref context.",
    )
    for flag, dest, _key, help_text in _FILTER_FLAGS:
        parser.add_argument(flag, dest=dest, default=None, help=help_text)
    parser.add_argument(
        "--current-episode", dest="current_episode", action="store_true",
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
    if parsed.current_episode:
        payload["current_episode"] = True
    return payload


def _filters_target(parsed: argparse.Namespace) -> TargetRef:
    # The --item filter rides the envelope target as a raw ref; the
    # dispatcher resolves it and the handler reads target.item_id.
    if parsed.item is not None:
        return item_target("item", parsed.item, parsed.project)
    return TargetRef(kind="global")


def _dispatch_filtered(
    function_id: str, prog: str, usage: str, args: List[str],
    *, with_limit: bool, default_limit: int = 50,
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    _add_filter_args(parser)
    if with_limit:
        parser.add_argument(
            "--limit", default=str(default_limit),
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


EVENTS_QUERY_USAGE = (
    "yoke events query [--event-name NAME] [--item PREFIX-N] "
    "[--session S] [--source-type T] [--event-kind K] [--agent A] "
    "[--service SVC] [--actor-id N] [--trace-id T] [--project P] "
    "[--min-severity LEVEL] [--since ISO|'2 hours ago'] [--until ...] "
    "[--current-episode] [--limit N] [--session-id S] [--json]"
)


def events_query(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.query.run", "yoke events query", EVENTS_QUERY_USAGE,
        args, with_limit=True, default_limit=50,
    )


EVENTS_TAIL_USAGE = "yoke events tail [--limit N] [--session-id S] [--json]"


def events_tail(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke events tail", description=EVENTS_TAIL_USAGE,
    )
    parser.add_argument(
        "--limit", default="20",
        help="Most-recent rows returned, 1..1000 (default 20).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EVENTS_TAIL_USAGE)
    if parsed is None:
        return 2
    try:
        limit = int(parsed.limit)
    except ValueError:
        return usage_error("--limit must be an integer")
    return dispatch_and_emit(
        function_id="events.tail.run",
        target=TargetRef(kind="global"),
        payload={"limit": limit},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


EVENTS_COUNT_USAGE = (
    "yoke events count [--event-name NAME] [--item PREFIX-N] "
    "[--session S] [--min-severity LEVEL] [--since ISO|'4 hours ago'] "
    "[--until ...] [--current-episode] [--session-id S] [--json]"
)


def events_count(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.count.run", "yoke events count", EVENTS_COUNT_USAGE,
        args, with_limit=False,
    )


EVENTS_ANOMALIES_USAGE = (
    "yoke events anomalies [--event-name NAME] [--item PREFIX-N] "
    "[--session S] [--since ISO|'24 hours ago'] [--until ...] "
    "[--limit N] [--session-id S] [--json]"
)


def events_anomalies(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.anomalies.run", "yoke events anomalies",
        EVENTS_ANOMALIES_USAGE, args, with_limit=True, default_limit=200,
    )
