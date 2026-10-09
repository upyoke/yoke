"""CLI adapters for reading and advancing epic dispatch chains."""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef


def _epic_target(parsed) -> TargetRef:
    return TargetRef(kind="epic_task", public_ref=parsed.epic)


def _write_body(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('body', '')}\n")
    for head in (response.result or {}).get("head_dispatch", []):
        holder = head.get("holder_session_id")
        suffix = f"; holder {holder}" if holder else ""
        stdout.write(
            f"head task {head.get('task_num')}: {head['decision']} — "
            f"{head['reason']}{suffix}\n"
        )


def _write_message(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('message', '')}\n")


def _dispatch(function_id, target, payload, parsed, writer=None) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
    )


EPIC_DISPATCH_CHAIN_GET_USAGE = (
    "yoke workflow-item epic-dispatch-chain get --epic PREFIX-N --worktree NAME "
    "[--session-id S] [--json]"
)


def epic_dispatch_chain_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-dispatch-chain get",
        description="Read one pipe row and its in-flight head's resume diagnostic; task acquire is the final gate.",
    )
    parser.add_argument("--epic", required=True)
    parser.add_argument("--worktree", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_DISPATCH_CHAIN_GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_dispatch_chain.get",
        _epic_target(parsed),
        {"worktree": parsed.worktree},
        parsed,
        _write_body,
    )


EPIC_DISPATCH_CHAIN_LIST_USAGE = (
    "yoke workflow-item epic-dispatch-chain list --epic PREFIX-N "
    "[--session-id S] [--json]"
)


def epic_dispatch_chain_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-dispatch-chain list",
        description="List pipe rows and in-flight head resume diagnostics; task acquire is the final gate.",
    )
    parser.add_argument("--epic", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_DISPATCH_CHAIN_LIST_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_dispatch_chain.list",
        _epic_target(parsed),
        {},
        parsed,
        _write_body,
    )


EPIC_DISPATCH_CHAIN_UPDATE_USAGE = (
    "yoke workflow-item epic-dispatch-chain update --epic PREFIX-N "
    "--worktree NAME --field FIELD (--value TEXT | --value-file PATH | --stdin) "
    "[--session-id S] [--json]"
)


def epic_dispatch_chain_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-dispatch-chain update",
        description="Update one whitelisted epic_dispatch_chains field.",
    )
    parser.add_argument("--epic", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--field", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(group, "--value", "--value-file", dest="value")
    group.add_argument("--stdin", action="store_true", help="Read value.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_DISPATCH_CHAIN_UPDATE_USAGE)
    if parsed is None:
        return 2
    try:
        value = (
            sys.stdin.read()
            if parsed.stdin
            else resolve_text_file(
                parsed.value,
                parsed.value_file,
                "--value-file",
            )
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return _dispatch(
        "workflow_item.epic_dispatch_chain.update",
        _epic_target(parsed),
        {
            "worktree": parsed.worktree,
            "field": parsed.field,
            "value": value or "",
        },
        parsed,
        _write_message,
    )


EPIC_DISPATCH_CHAIN_REFRESH_ACTIVATION_USAGE = (
    "yoke workflow-item epic-dispatch-chain refresh-activation --epic PREFIX-N "
    "--worktree NAME --task-num N [--session-id S] [--json]"
)


def epic_dispatch_chain_refresh_activation(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-dispatch-chain refresh-activation",
        description="Refresh current task, attempt, and timestamp on activation.",
    )
    parser.add_argument("--epic", required=True)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--task-num", type=int, required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        EPIC_DISPATCH_CHAIN_REFRESH_ACTIVATION_USAGE,
    )
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_dispatch_chain.refresh_activation",
        _epic_target(parsed),
        {"worktree": parsed.worktree, "task_num": parsed.task_num},
        parsed,
        _write_message,
    )


EPIC_DISPATCH_CHAIN_ADVANCE_USAGE = (
    "yoke workflow-item epic-dispatch-chain advance --epic PREFIX-N "
    "--worktree NAME [--session-id S] [--json]"
)


def epic_dispatch_chain_advance(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-dispatch-chain advance",
        description="Atomically advance one dispatch chain to its next task.",
    )
    parser.add_argument("--epic", required=True)
    parser.add_argument("--worktree", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        EPIC_DISPATCH_CHAIN_ADVANCE_USAGE,
    )
    if parsed is None:
        return 2

    def _write_advance(response, stdout, stderr) -> None:
        result = response.result or {}
        stdout.write(
            f"{result.get('current_index', '')}|{result.get('next_task_num', '')}\n"
        )

    return _dispatch(
        "workflow_item.epic_dispatch_chain.advance",
        _epic_target(parsed),
        {"worktree": parsed.worktree},
        parsed,
        _write_advance,
    )


__all__ = [
    "EPIC_DISPATCH_CHAIN_ADVANCE_USAGE",
    "EPIC_DISPATCH_CHAIN_GET_USAGE",
    "EPIC_DISPATCH_CHAIN_LIST_USAGE",
    "EPIC_DISPATCH_CHAIN_REFRESH_ACTIVATION_USAGE",
    "EPIC_DISPATCH_CHAIN_UPDATE_USAGE",
    "epic_dispatch_chain_advance",
    "epic_dispatch_chain_get",
    "epic_dispatch_chain_list",
    "epic_dispatch_chain_refresh_activation",
    "epic_dispatch_chain_update",
]
