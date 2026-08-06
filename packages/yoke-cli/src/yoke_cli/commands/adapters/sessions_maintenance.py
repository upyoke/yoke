"""CLI adapters for guarded session closeout and stale reclamation."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


SESSIONS_END_IF_EMPTY_USAGE = (
    "yoke sessions end-if-empty [--triggered-by SOURCE] "
    "[--session-id S] [--json]"
)
SESSIONS_RECLAIM_STALE_USAGE = (
    "yoke sessions reclaim-stale --confirm [--project-ids ID,ID,...] "
    "[--session-id S] [--json]"
)


def sessions_end_if_empty(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions end-if-empty",
        description=SESSIONS_END_IF_EMPTY_USAGE,
    )
    parser.add_argument("--triggered-by", default="cli")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_END_IF_EMPTY_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.end_if_empty",
        target=TargetRef(kind="global"),
        payload={"triggered_by": parsed.triggered_by},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _project_ids(raw: str | None) -> list[int] | None:
    if raw is None:
        return None
    try:
        values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    except ValueError as exc:
        raise ValueError("--project-ids must be comma-separated integers") from exc
    if not values or any(value < 1 for value in values):
        raise ValueError("--project-ids must contain positive integers")
    return values


def sessions_reclaim_stale(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions reclaim-stale",
        description=SESSIONS_RECLAIM_STALE_USAGE,
    )
    parser.add_argument("--confirm", action="store_true", required=True)
    parser.add_argument("--project-ids", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_RECLAIM_STALE_USAGE)
    if parsed is None:
        return 2
    try:
        project_ids = _project_ids(parsed.project_ids)
    except ValueError as exc:
        return usage_error(str(exc))
    payload = {"confirm": parsed.confirm}
    if project_ids is not None:
        payload["project_ids"] = project_ids
    return dispatch_and_emit(
        function_id="sessions.reclaim_stale",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "SESSIONS_END_IF_EMPTY_USAGE",
    "SESSIONS_RECLAIM_STALE_USAGE",
    "sessions_end_if_empty",
    "sessions_reclaim_stale",
]
