"""``yoke db read`` diagnostic SQL adapter."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.connection_authority_teaching import DB_GROUP_TEACHING


DB_READ_USAGE = (
    'yoke db read "SELECT ..." [--format human|json|lines] [--session-id S] [--json]'
)

_DB_READ_HELP = (
    "Run one read-only diagnostic SQL statement through the registered "
    "function dispatcher. Default output labels the query result. "
    "``--format json`` emits the result payload; ``--format lines`` emits one pipe-delimited row per line "
    "for shell consumption. ``--json`` emits the full typed "
    "FunctionCallResponse envelope. A query that reads item ids (items.id or any "
    "*item_id column) without item_refs warns, on success and on failure: "
    "join item_refs on item_id and select public_ref to show PREFIX-N refs.\n\n"
    + DB_GROUP_TEACHING
)


def _write_lines(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    if not response.success:
        message = response.error.message if response.error else "db read failed"
        print(message, file=stderr)
        return
    for warning in response.warnings:
        print(f"warning: {warning.code}: {warning.detail}", file=stderr)
    result = response.result or {}
    columns = [str(column) for column in result.get("columns", [])]
    for row in result.get("rows", []):
        values = []
        for index, column in enumerate(columns):
            if isinstance(row, dict):
                value = row.get(column)
            elif isinstance(row, (list, tuple)) and index < len(row):
                value = row[index]
            else:
                value = None
            values.append("" if value is None else str(value))
        print("|".join(values), file=stdout)


def _write_json(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    print(json.dumps(response.result, sort_keys=True), file=stdout)
    for warning in response.warnings:
        print(f"warning: {warning.code}: {warning.detail}", file=stderr)


def db_read(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db read",
        description=f"{DB_READ_USAGE}\n\n{_DB_READ_HELP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sql", help="Read-only SQL diagnostic query.")
    parser.add_argument(
        "--format",
        choices=("human", "json", "lines"),
        default="human",
        help=(
            "Result format (default: human). 'lines' emits pipe-delimited "
            "rows in query-column order."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DB_READ_USAGE)
    if parsed is None:
        return 2
    sql = parsed.sql.strip()
    if not sql:
        return usage_error("db read requires a SQL string")
    if parsed.json_mode and parsed.format == "lines":
        return usage_error("db read --json cannot be combined with --format lines")
    payload: Dict[str, str] = {"sql": sql}
    return dispatch_and_emit(
        function_id="db.read.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer={"lines": _write_lines, "json": _write_json}.get(parsed.format),
        machine_mode=parsed.format != "human",
    )


__all__ = ["DB_READ_USAGE", "db_read"]
