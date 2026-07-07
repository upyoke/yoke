"""``yoke workflow-item epic-progress-note ...`` + ``yoke epic-tasks list``.

Three adapters split out of :mod:`yoke_cli.commands.adapters.epic_task` to
keep each authored file under the 350-line cap:

* ``workflow_item.epic_progress_note.append``
* ``workflow_item.epic_progress_note.list``
* ``epic_tasks.list.run``
"""

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


__all__ = [
    "epic_progress_note_append", "epic_progress_note_list", "epic_tasks_list",
    "EPIC_PROGRESS_NOTE_APPEND_USAGE", "EPIC_PROGRESS_NOTE_LIST_USAGE",
    "EPIC_TASKS_LIST_USAGE",
]


def _epic_task_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--epic", type=int, required=True,
                        help="Epic id (bare integer).")
    parser.add_argument("--task-num", dest="task_num", type=int, required=True,
                        help="Task number within the epic (1-based).")


def _epic_task_target(parsed) -> TargetRef:
    return TargetRef(
        kind="epic_task", epic_id=int(parsed.epic), task_num=int(parsed.task_num),
    )


EPIC_PROGRESS_NOTE_APPEND_USAGE = (
    "yoke workflow-item epic-progress-note append --epic N --task-num N "
    "--note-num N (--body TEXT | --body-file PATH | --stdin) "
    "[--commit-hash SHA] [--session-id S] [--json]"
)


def epic_progress_note_append(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-progress-note append",
        description=EPIC_PROGRESS_NOTE_APPEND_USAGE,
    )
    _epic_task_target_flags(parser)
    parser.add_argument("--note-num", dest="note_num", type=int, required=True,
                        help="1-based note number within the task.")
    body_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(body_group, "--body", "--body-file", dest="body",
                       help_text="Note body (Markdown).")
    body_group.add_argument("--stdin", action="store_true",
                            help="Read body from stdin.")
    parser.add_argument("--commit-hash", dest="commit_hash", default="",
                        help="Optional binding commit SHA.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_PROGRESS_NOTE_APPEND_USAGE)
    if parsed is None:
        return 2
    try:
        body = sys.stdin.read() if parsed.stdin else resolve_text_file(
            parsed.body, parsed.body_file, "--body-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="workflow_item.epic_progress_note.append",
        target=_epic_task_target(parsed),
        payload={
            "note_num": parsed.note_num, "body": body,
            "commit_hash": parsed.commit_hash,
        },
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


EPIC_PROGRESS_NOTE_LIST_USAGE = (
    "yoke workflow-item epic-progress-note list --epic N --task-num N "
    "[--limit N] [--session-id S] [--json]"
)


def epic_progress_note_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-progress-note list",
        description=EPIC_PROGRESS_NOTE_LIST_USAGE,
    )
    _epic_task_target_flags(parser)
    parser.add_argument("--limit", type=int, default=0,
                        help="Optional max number of entries.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_PROGRESS_NOTE_LIST_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="workflow_item.epic_progress_note.list",
        target=_epic_task_target(parsed),
        payload={"limit": int(parsed.limit)},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


EPIC_TASKS_LIST_USAGE = (
    "yoke epic-tasks list --epic N [--session-id S] [--json]"
)


def epic_tasks_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke epic-tasks list", description=EPIC_TASKS_LIST_USAGE,
    )
    parser.add_argument("--epic", type=int, required=True, help="Epic id.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASKS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        for task in (response.result or {}).get("tasks", []):
            stdout.write(
                f"{task.get('task_num', '')}|{task.get('title', '')}|"
                f"{task.get('status', '')}|{task.get('worktree', '')}|"
                f"{task.get('dependencies', '')}\n"
            )

    return dispatch_and_emit(
        function_id="epic_tasks.list.run",
        target=TargetRef(kind="epic_task", epic_id=int(parsed.epic)),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
