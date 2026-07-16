"""Explicit archive-only adapters for deployment receipt reads."""

from __future__ import annotations

import argparse
import json
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


FLOW_RECEIPT_GET_USAGE = (
    "yoke deployment-flow-receipts get FLOW-ID [--session-id S] [--json]"
)
FLOW_RECEIPT_LIST_USAGE = (
    "yoke deployment-flow-receipts list [--project P] "
    "[--session-id S] [--json]"
)
RUN_RECEIPT_GET_USAGE = (
    "yoke deployment-run-receipts get RUN-ID [--session-id S] [--json]"
)
RUN_RECEIPT_LIST_USAGE = (
    "yoke deployment-run-receipts list [--project P] [--flow FLOW] "
    "[--status STATUS] [--session-id S] [--json]"
)

USAGE_BY_FUNCTION_ID = {
    "deployment_flow_receipts.get": FLOW_RECEIPT_GET_USAGE,
    "deployment_flow_receipts.list": FLOW_RECEIPT_LIST_USAGE,
    "deployment_run_receipts.get": RUN_RECEIPT_GET_USAGE,
    "deployment_run_receipts.list": RUN_RECEIPT_LIST_USAGE,
}


def _pipe(fields: list[str], row: dict[str, Any]) -> str:
    return "|".join(
        "" if row.get(field) is None else str(row.get(field))
        for field in fields
    )


def _get_adapter(
    args: List[str],
    *,
    program: str,
    usage: str,
    id_name: str,
    function_id: str,
) -> int:
    parser = argparse.ArgumentParser(prog=program, description=usage)
    parser.add_argument(id_name)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        receipt = (response.result or {}).get("receipt") or {}
        print(
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False,
            ),
            file=stdout,
        )
        return None

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload={id_name: getattr(parsed, id_name)},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_flow_receipts_get(args: List[str]) -> int:
    return _get_adapter(
        args,
        program="yoke deployment-flow-receipts get",
        usage=FLOW_RECEIPT_GET_USAGE,
        id_name="flow_id",
        function_id="deployment_flow_receipts.get",
    )


def deployment_run_receipts_get(args: List[str]) -> int:
    return _get_adapter(
        args,
        program="yoke deployment-run-receipts get",
        usage=RUN_RECEIPT_GET_USAGE,
        id_name="run_id",
        function_id="deployment_run_receipts.get",
    )


def _list_adapter(
    args: List[str],
    *,
    program: str,
    usage: str,
    function_id: str,
    include_run_filters: bool,
) -> int:
    parser = argparse.ArgumentParser(prog=program, description=usage)
    parser.add_argument("--project", default=None)
    if include_run_filters:
        parser.add_argument("--flow", default=None)
        parser.add_argument("--status", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(_pipe(fields, row), file=stdout)
        return None

    payload = {}
    for key in ("project", "flow", "status"):
        value = getattr(parsed, key, None)
        if value is not None:
            payload[key] = value
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_flow_receipts_list(args: List[str]) -> int:
    return _list_adapter(
        args,
        program="yoke deployment-flow-receipts list",
        usage=FLOW_RECEIPT_LIST_USAGE,
        function_id="deployment_flow_receipts.list",
        include_run_filters=False,
    )


def deployment_run_receipts_list(args: List[str]) -> int:
    return _list_adapter(
        args,
        program="yoke deployment-run-receipts list",
        usage=RUN_RECEIPT_LIST_USAGE,
        function_id="deployment_run_receipts.list",
        include_run_filters=True,
    )


__all__ = [
    "FLOW_RECEIPT_GET_USAGE",
    "FLOW_RECEIPT_LIST_USAGE",
    "RUN_RECEIPT_GET_USAGE",
    "RUN_RECEIPT_LIST_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "deployment_flow_receipts_get",
    "deployment_flow_receipts_list",
    "deployment_run_receipts_get",
    "deployment_run_receipts_list",
]
