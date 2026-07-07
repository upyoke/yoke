"""``yoke db read`` diagnostic SQL adapter."""

from __future__ import annotations

import argparse
from typing import Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


DB_READ_USAGE = 'yoke db read "SELECT ..." [--session-id S] [--json]'

_DB_READ_HELP = """\
Run one read-only diagnostic SQL statement through the registered function
dispatcher. Default output is the handler result payload as JSON; --json emits
the full typed FunctionCallResponse envelope.
"""


def db_read(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke db read",
        description=f"{DB_READ_USAGE}\n\n{_DB_READ_HELP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("sql", help="Read-only SQL diagnostic query.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DB_READ_USAGE)
    if parsed is None:
        return 2
    sql = parsed.sql.strip()
    if not sql:
        return usage_error("db read requires a SQL string")
    payload: Dict[str, str] = {"sql": sql}
    return dispatch_and_emit(
        function_id="db.read.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = ["DB_READ_USAGE", "db_read"]
