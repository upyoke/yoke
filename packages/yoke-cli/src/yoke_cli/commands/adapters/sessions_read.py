"""``yoke sessions list`` adapter (read-only session roster).

Split from :mod:`yoke_cli.commands.adapters.sessions` (which owns the
begin / touch / checkpoint / offer wrappers) to keep that module under
the authored-file line cap.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


SESSIONS_LIST_USAGE = (
    "yoke sessions list [--project P] [--liveness active|stale|ended] "
    "[--limit N] [--session-id S] [--json]"
)


def _cell(row: Dict[str, Any], field: str) -> str:
    value = row.get(field)
    if field == "claims":
        return ",".join(
            str(claim.get("target") or "") for claim in (value or [])
        )
    return "" if value is None else str(value)


def sessions_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions list", description=SESSIONS_LIST_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--liveness", default=None)
    parser.add_argument("--limit", type=int, default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(
                "|".join(_cell(row, field) for field in fields),
                file=stdout,
            )
        return None

    payload: Dict[str, Any] = {}
    for key in ("project", "liveness"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    return dispatch_and_emit(
        function_id="sessions.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["SESSIONS_LIST_USAGE", "sessions_list"]
