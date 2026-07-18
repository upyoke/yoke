"""Epic task, dispatch-chain, and conduct pipeline adapters."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    split_comma,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.adapters.epic_dispatch_chain import *  # noqa: F403


def _epic_task_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--epic", type=int, required=True, help="Epic id.")
    parser.add_argument("--task-num", type=int, required=True,
                        help="Task number within the epic.")


def _epic_task_target(parsed) -> TargetRef:
    return TargetRef(
        kind="epic_task", epic_id=int(parsed.epic),
        task_num=int(parsed.task_num),
    )


def _epic_target(parsed) -> TargetRef:
    return TargetRef(kind="epic_task", epic_id=int(parsed.epic))


def _write_body(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('body', '')}\n")


def _write_message(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('message', '')}\n")


def _dispatch(function_id, target, payload, parsed, writer=None) -> int:
    return dispatch_and_emit(
        function_id=function_id, target=target, payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=writer,
    )


EPIC_TASK_GET_USAGE = (
    "yoke workflow-item epic-task get --epic N --task-num N "
    "[--session-id S] [--json]"
)

def epic_task_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task get",
        description="Read one pipe-delimited epic_tasks row.",
    )
    _epic_task_flags(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_task.get", _epic_task_target(parsed), {},
        parsed, _write_body,
    )


EPIC_TASK_SIMULATION_GET_USAGE = (
    "yoke workflow-item epic-task simulation-get --epic N --phase P "
    "[--session-id S] [--json]"
)

def epic_task_simulation_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task simulation-get",
        description="Read the latest pipe-delimited simulation row.",
    )
    parser.add_argument("--epic", type=int, required=True, help="Epic id.")
    parser.add_argument("--phase", required=True, help="Simulation phase.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_SIMULATION_GET_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_task.simulation_get", _epic_target(parsed),
        {"phase": parsed.phase}, parsed, _write_body,
    )


EPIC_TASK_FILE_ADD_USAGE = (
    "yoke workflow-item epic-task file-add --epic N --task-num N "
    "--file-path PATH [--action ACTION] [--session-id S] [--json]"
)

def epic_task_file_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task file-add",
        description="Add or update one epic_task_files row.",
    )
    _epic_task_flags(parser)
    parser.add_argument("--file-path", required=True, help="Task file path.")
    parser.add_argument("--action", default="", help="File action label.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_FILE_ADD_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "workflow_item.epic_task.file_add", _epic_task_target(parsed),
        {"file_path": parsed.file_path, "action": parsed.action},
        parsed, _write_message,
    )


EPIC_TASK_HISTORY_INSERT_USAGE = (
    "yoke workflow-item epic-task history-insert --epic N --task-num N "
    "--from-status S --to-status S [--note TEXT | --note-file PATH] "
    "[--session-id S] [--json]"
)

def epic_task_history_insert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task history-insert",
        description="Record one epic task status-history transition.",
    )
    _epic_task_flags(parser)
    parser.add_argument("--from-status", required=True)
    parser.add_argument("--to-status", required=True)
    group = parser.add_mutually_exclusive_group()
    add_text_file_pair(group, "--note", "--note-file", dest="note")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_HISTORY_INSERT_USAGE)
    if parsed is None:
        return 2
    try:
        note = resolve_text_file(parsed.note, parsed.note_file, "--note-file")
    except ValueError as exc:
        return usage_error(str(exc))
    return _dispatch(
        "workflow_item.epic_task.history_insert", _epic_task_target(parsed),
        {
            "from_status": parsed.from_status,
            "to_status": parsed.to_status,
            "note": note or "",
        },
        parsed, _write_message,
    )


CONDUCT_EPIC_TASK_UPDATE_STATUS_USAGE = (
    "yoke conduct epic-task update-status --epic N --task-num N "
    "--status STATUS [--note TEXT | --note-file PATH] [--no-rebuild] "
    "[--no-github] [--no-derive] [--claim-bypass SOURCE] "
    "[--session-id S] [--json]"
)


def conduct_epic_task_update_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke conduct epic-task update-status",
        description="Run the full conduct epic-task status pipeline.",
    )
    _epic_task_flags(parser)
    parser.add_argument("--status", required=True)
    group = parser.add_mutually_exclusive_group()
    add_text_file_pair(group, "--note", "--note-file", dest="note")
    parser.add_argument("--no-rebuild", action="store_true")
    parser.add_argument("--no-github", action="store_true")
    parser.add_argument("--no-derive", action="store_true")
    parser.add_argument("--claim-bypass", default="")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CONDUCT_EPIC_TASK_UPDATE_STATUS_USAGE,
    )
    if parsed is None:
        return 2
    try:
        note = resolve_text_file(parsed.note, parsed.note_file, "--note-file")
    except ValueError as exc:
        return usage_error(str(exc))
    return _dispatch(
        "conduct.epic_task.update_status", _epic_task_target(parsed),
        {
            "status": parsed.status,
            "note": note or "",
            "no_rebuild": parsed.no_rebuild,
            "no_github": parsed.no_github,
            "no_derive": parsed.no_derive,
            "claim_bypass": parsed.claim_bypass,
        },
        parsed, lambda r, out, err: out.write((r.result or {}).get("stdout", "")),
    )


CONDUCT_EPIC_PROCEED_TRIAGE_HANDOFF_USAGE = (
    "yoke conduct epic proceed-triage-handoff --epic N "
    "[--recommendation R] [--gap-summary S] [--filed-tickets T1,T2] "
    "[--session-id S] [--json]"
)


def conduct_epic_proceed_triage_handoff(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke conduct epic proceed-triage-handoff",
        description="Record accepted simulation gaps and hand off the epic.",
    )
    parser.add_argument("--epic", type=int, required=True)
    parser.add_argument("--recommendation", default="PROCEED")
    parser.add_argument("--gap-summary", default="")
    parser.add_argument("--filed-tickets", default="")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, CONDUCT_EPIC_PROCEED_TRIAGE_HANDOFF_USAGE,
    )
    if parsed is None:
        return 2
    return _dispatch(
        "conduct.epic.proceed_triage_handoff", _epic_target(parsed),
        {
            "recommendation": parsed.recommendation,
            "gap_summary": parsed.gap_summary,
            "filed_ticket_ids": split_comma(parsed.filed_tickets),
            "session_id": parsed.session_id,
        },
        parsed, lambda r, out, err: out.write((r.result or {}).get("stdout", "")),
    )


__all__ = [
    name for name in globals()
    if name.endswith("_USAGE")
    or name.startswith(("epic_task_", "epic_dispatch_", "conduct_epic_"))
]
