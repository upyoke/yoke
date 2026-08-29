"""CLI adapters for deployment inventory and progress inspection."""

from __future__ import annotations

import argparse
import json
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


DEPLOYMENT_FLOWS_LIST_USAGE = (
    "yoke deployment-flows list [--project P] [--include-disabled] "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE = (
    "yoke deployment-runs find-by-item ITEM [--project P] [--status STATUS] "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_STAGES_USAGE = (
    "yoke deployment-runs stages RUN-ID [--session-id S] [--json]"
)
DEPLOYMENT_RUNS_FAILURE_TRACE_USAGE = (
    "yoke deployment-runs failure-trace RUN-ID [--session-id S] [--json]"
)


def _pipe(fields: list[str], row: dict[str, Any]) -> str:
    return "|".join("" if row.get(field) is None else str(row.get(field))
                    for field in fields)


def deployment_flows_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows list",
        description=DEPLOYMENT_FLOWS_LIST_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--include-disabled", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_FLOWS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(_pipe(fields, row), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_flows.list",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "include_disabled": parsed.include_disabled,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_find_by_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs find-by-item",
        description=DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE,
    )
    parser.add_argument("item")
    parser.add_argument("--project", default=None)
    parser.add_argument("--status", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(_pipe(fields, row), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.find_by_item",
        target=item_target("item", parsed.item, parsed.project),
        payload={"status": parsed.status},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_stages(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs stages",
        description=DEPLOYMENT_RUNS_STAGES_USAGE,
    )
    parser.add_argument("run_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_STAGES_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        for stage in (response.result or {}).get("stages") or []:
            print(json.dumps(stage, sort_keys=True), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.stages",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_failure_trace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs failure-trace",
        description=(
            "Walk relayed GitHub Actions runs to the terminal failing job, "
            "preserving every reached run URL and any partial-stop reason."
        ),
    )
    parser.add_argument("run_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEPLOYMENT_RUNS_FAILURE_TRACE_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        if result.get("complete"):
            print(f"Terminal failing job: {result.get('terminal_job')}", file=stdout)
            print(f"Terminal error: {result.get('terminal_error')}", file=stdout)
        else:
            print(f"Failure trace stopped: {result.get('stop_reason')}", file=stdout)
            print(f"Recovery: {result.get('recovery')}", file=stdout)
        print(
            f"Failure chain for {result.get('deployment_run_id')} "
            f"(stage {result.get('stage')}):",
            file=stdout,
        )
        for index, hop in enumerate(result.get("chain") or [], start=1):
            job = f" — {hop.get('failed_job')}" if hop.get("failed_job") else ""
            print(f"  {index}. {hop.get('url')}{job}", file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.failure_trace",
        target=TargetRef(
            kind="deployment_run",
            deployment_run_id=parsed.run_id,
        ),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "DEPLOYMENT_FLOWS_LIST_USAGE",
    "DEPLOYMENT_RUNS_FIND_BY_ITEM_USAGE",
    "DEPLOYMENT_RUNS_FAILURE_TRACE_USAGE",
    "DEPLOYMENT_RUNS_STAGES_USAGE",
    "deployment_flows_list",
    "deployment_runs_find_by_item",
    "deployment_runs_failure_trace",
    "deployment_runs_stages",
]
