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
from yoke_cli.transport.human_values import write_human

from yoke_cli.commands.adapters.events_query_filters import (
    _dispatch_filtered,
)

import argparse
import json
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


__all__ = [
    "events_emit",
    "events_query",
    "events_tail",
    "events_count",
    "events_anomalies",
    "EVENTS_EMIT_USAGE",
    "EVENTS_QUERY_USAGE",
    "EVENTS_TAIL_USAGE",
    "EVENTS_COUNT_USAGE",
    "EVENTS_ANOMALIES_USAGE",
]


EVENTS_EMIT_USAGE = (
    "yoke events emit --name NAME --kind KIND --type TYPE "
    "--source-type SOURCE [--severity LEVEL] [--outcome OUTCOME] "
    "[--project P] [--item PREFIX-N] [--task-num N] [--agent A] [--tool-name T] "
    "[--org-id ID] [--environment ENV] [--request-id ID] [--trace-id ID] "
    "[--parent-id ID] [--tool-use-id ID] [--turn-id ID] [--hook-event-name NAME] "
    "[--anomaly-flags FLAGS] [--duration-ms MS] [--exit-code CODE] "
    "[--context JSON] [--error-context JSON] [--full] [--session-id S] [--json]"
)

_EMIT_FIELD_METAVARS = {
    "org-id": "ID",
    "environment": "ENV",
    "request-id": "ID",
    "project": "P",
    "agent": "A",
    "tool-name": "T",
    "trace-id": "ID",
    "parent-id": "ID",
    "anomaly-flags": "FLAGS",
    "tool-use-id": "ID",
    "turn-id": "ID",
    "hook-event-name": "NAME",
}


def _add_emit_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--name", required=True, help="Event name.")
    parser.add_argument("--kind", required=True, help="Event kind.")
    parser.add_argument("--type", required=True, help="Event type.")
    parser.add_argument(
        "--source-type",
        required=True,
        metavar="SOURCE",
        help="Kind of source that produced the event.",
    )
    parser.add_argument(
        "--severity", default="INFO", metavar="LEVEL", help="Event severity; default: INFO."
    )
    parser.add_argument(
        "--outcome", default="completed", help="Event outcome; default: completed."
    )
    for flag, metavar in _EMIT_FIELD_METAVARS.items():
        parser.add_argument(
            f"--{flag}",
            default=None,
            metavar=metavar,
            help=f"Value for the event's {flag} field.",
        )
    parser.add_argument(
        "--item",
        dest="public_ref",
        default=None,
        metavar="PREFIX-N",
        help="Item the event belongs to (PREFIX-N).",
    )
    parser.add_argument(
        "--task-num",
        type=int,
        default=None,
        metavar="N",
        help="Task number the event belongs to.",
    )
    parser.add_argument(
        "--duration-ms",
        type=int,
        default=None,
        metavar="MS",
        help="How long the work took, in milliseconds.",
    )
    parser.add_argument(
        "--exit-code",
        type=int,
        default=None,
        metavar="CODE",
        help="Exit code of the work the event reports.",
    )
    parser.add_argument(
        "--context", default=None, metavar="JSON", help="Extra detail for the event, as JSON."
    )
    parser.add_argument(
        "--error-context",
        default=None,
        metavar="JSON",
        help="Error detail for the event, as JSON.",
    )


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
        usage=EVENTS_EMIT_USAGE,
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

    if parsed.public_ref is not None:
        parsed.public_ref = item_target(
            "item", parsed.public_ref, parsed.project
        ).public_ref
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
        "org_id",
        "environment",
        "request_id",
        "project",
        "public_ref",
        "task_num",
        "agent",
        "tool_name",
        "duration_ms",
        "exit_code",
        "trace_id",
        "parent_id",
        "anomaly_flags",
        "tool_use_id",
        "turn_id",
        "hook_event_name",
    ):
        value = getattr(parsed, attr)
        if value is not None and str(value) != "":
            payload[attr] = value
    project = client_project_context(parsed.project)
    if project:
        payload["project"] = project

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("reason") not in ("", None, "severity_filtered"):
            write_human(result, stdout)

    return dispatch_and_emit(
        function_id="events.emit",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


_FILTER_USAGE = (
    "[--event-name NAME] [--item PREFIX-N] [--project P] "
    "[--session S] [--source-type T] [--event-kind K] [--agent A] "
    "[--service SVC] [--actor-id N] [--trace-id T] [--tool-use-id ID] "
    "[--turn-id ID] [--hook-event-name NAME] [--min-severity LEVEL] "
    "[--since WHEN] [--until WHEN] [--current-episode]"
)
EVENTS_QUERY_USAGE = (
    f"yoke events query {_FILTER_USAGE} [--limit N] [--full] [--session-id S] [--json]"
)


def events_query(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.query.run",
        "yoke events query",
        EVENTS_QUERY_USAGE,
        args,
        with_limit=True,
        default_limit=50,
    )


EVENTS_TAIL_USAGE = (
    "yoke events tail [--limit N] [--project P] [--full] [--session-id S] [--json]"
)


def events_tail(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke events tail",
        usage=EVENTS_TAIL_USAGE,
    )
    parser.add_argument(
        "--limit",
        default="20",
        metavar="N",
        help="Most-recent rows returned, 1..1000 (default 20).",
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="P",
        help="Project slug or id (default: the checkout's mapped project).",
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
    project = client_project_context(parsed.project)
    payload: Dict[str, Any] = {"limit": limit}
    if project:
        payload["project"] = project
    return dispatch_and_emit(
        function_id="events.tail.run",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


EVENTS_COUNT_USAGE = (
    f"yoke events count {_FILTER_USAGE} [--full] [--session-id S] [--json]"
)


def events_count(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.count.run",
        "yoke events count",
        EVENTS_COUNT_USAGE,
        args,
        with_limit=False,
    )


EVENTS_ANOMALIES_USAGE = (
    f"yoke events anomalies {_FILTER_USAGE} [--limit N] [--full] "
    "[--session-id S] [--json]"
)


def events_anomalies(args: List[str]) -> int:
    return _dispatch_filtered(
        "events.anomalies.run",
        "yoke events anomalies",
        EVENTS_ANOMALIES_USAGE,
        args,
        with_limit=True,
        default_limit=200,
    )
