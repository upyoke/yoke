"""``yoke db read`` diagnostic SQL adapter."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


DB_READ_USAGE = (
    'yoke db read "SELECT ..." [--format json|lines] '
    '[--session-id S] [--json]'
)

_DB_READ_HELP = """\
Run one read-only diagnostic SQL statement through the registered function
dispatcher. Default output is the handler result payload as JSON; ``--format
lines`` emits one pipe-delimited row per line for shell consumption. ``--json``
emits the full typed FunctionCallResponse envelope.
"""


def _write_lines(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    if not response.success:
        message = response.error.message if response.error else "db read failed"
        print(message, file=stderr)
        return
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


def db_read(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db read",
        description=f"{DB_READ_USAGE}\n\n{_DB_READ_HELP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sql", help="Read-only SQL diagnostic query.")
    parser.add_argument(
        "--format",
        choices=("json", "lines"),
        default="json",
        help=(
            "Result format (default: json). 'lines' emits pipe-delimited "
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
    if parsed.json_mode and parsed.format != "json":
        return usage_error("db read --json cannot be combined with --format lines")
    payload: Dict[str, str] = {"sql": sql}
    return dispatch_and_emit(
        function_id="db.read.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_lines if parsed.format == "lines" else None,
    )


__all__ = ["DB_READ_USAGE", "db_read"]
