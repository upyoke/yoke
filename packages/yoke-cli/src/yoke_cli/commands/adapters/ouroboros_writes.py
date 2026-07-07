"""``yoke ouroboros`` write/lifecycle adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef


OUROBOROS_ENTRY_INSERT_USAGE = (
    "yoke ouroboros entry insert --agent A --category C "
    "(--observation TEXT | --observation-file PATH | --stdin) "
    "[--context TEXT] [--timestamp TS] [--project P] [--session-id S] [--json]"
)
OUROBOROS_ENTRY_MARK_REVIEWED_USAGE = (
    "yoke ouroboros entry mark-reviewed ENTRY_ID [--session-id S] [--json]"
)
OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE = (
    "yoke ouroboros entry mark-archived (--all-reviewed | ENTRY_ID) "
    "[--session-id S] [--json]"
)
OUROBOROS_WRAPUP_LIST_USAGE = (
    "yoke ouroboros wrapup list [--session-id S] [--json]"
)


__all__ = [
    "ouroboros_entry_insert",
    "ouroboros_entry_mark_reviewed",
    "ouroboros_entry_mark_archived",
    "ouroboros_wrapup_list",
    "OUROBOROS_ENTRY_INSERT_USAGE",
    "OUROBOROS_ENTRY_MARK_REVIEWED_USAGE",
    "OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE",
    "OUROBOROS_WRAPUP_LIST_USAGE",
]


def ouroboros_entry_insert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry insert",
        description=OUROBOROS_ENTRY_INSERT_USAGE,
    )
    parser.add_argument("--agent", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--context")
    parser.add_argument("--timestamp")
    parser.add_argument("--project")
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group,
        "--observation",
        "--observation-file",
        dest="observation",
        help_text="Observation body. Use --observation-file to read a path.",
    )
    group.add_argument("--stdin", action="store_true", help="Read body from stdin.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_ENTRY_INSERT_USAGE)
    if parsed is None:
        return 2
    if parsed.stdin:
        import sys

        observation = sys.stdin.read()
    else:
        try:
            observation = resolve_text_file(
                parsed.observation,
                parsed.observation_file,
                "--observation-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "agent": parsed.agent,
        "category": parsed.category,
        "observation": observation,
    }
    for key in ("context", "timestamp", "project"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("entry_id", ""), file=stdout)

    return dispatch_and_emit(
        function_id="ouroboros.entry.insert",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def ouroboros_entry_mark_reviewed(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry mark-reviewed",
        description=OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    )
    parser.add_argument("entry_id", type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, OUROBOROS_ENTRY_MARK_REVIEWED_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="ouroboros.entry.mark_reviewed",
        target=TargetRef(kind="global"),
        payload={"entry_id": parsed.entry_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def ouroboros_entry_mark_archived(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros entry mark-archived",
        description=OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    )
    parser.add_argument("entry_id", nargs="?", type=int)
    parser.add_argument("--all-reviewed", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, OUROBOROS_ENTRY_MARK_ARCHIVED_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.all_reviewed and parsed.entry_id is not None:
        return usage_error("pass either --all-reviewed or ENTRY_ID, not both")
    if not parsed.all_reviewed and parsed.entry_id is None:
        return usage_error("pass --all-reviewed or ENTRY_ID")
    payload = {"all_reviewed": bool(parsed.all_reviewed)}
    if parsed.entry_id is not None:
        payload["entry_id"] = parsed.entry_id

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="ouroboros.entry.mark_archived",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def ouroboros_wrapup_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros wrapup list",
        description=OUROBOROS_WRAPUP_LIST_USAGE,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, OUROBOROS_WRAPUP_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        for row in (response.result or {}).get("rows", []):
            print(
                "|".join(
                    [
                        str(row.get("id", "")),
                        str(row.get("session_timestamp", "")),
                        str(row.get("created_at", "")),
                    ]
                ),
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="ouroboros.wrapup.list",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
