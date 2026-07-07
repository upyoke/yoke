"""``yoke workflow-item epic-task ...`` flag adapters.

Six adapters covering the ``workflow_item.epic_task.*`` family:
``body_replace``, ``split``, ``reassign``, ``add``, ``remove``,
``metadata_update``. Progress notes + epic-tasks list live in the
sibling :mod:`yoke_cli.commands.adapters.epic_progress` module (the file
budget cap forced the split).

All entries target ``kind="epic_task"`` with ``epic_id`` (and
``task_num`` except for ``add`` which creates one).
"""

from __future__ import annotations

import argparse
import json
import sys
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


__all__ = [
    "epic_task_body_replace", "epic_task_split", "epic_task_reassign",
    "epic_task_add", "epic_task_remove", "epic_task_metadata_update",
    "EPIC_TASK_BODY_REPLACE_USAGE", "EPIC_TASK_SPLIT_USAGE",
    "EPIC_TASK_REASSIGN_USAGE", "EPIC_TASK_ADD_USAGE",
    "EPIC_TASK_REMOVE_USAGE", "EPIC_TASK_METADATA_UPDATE_USAGE",
]


def _epic_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--epic", type=int, required=True,
                        help="Epic id (bare integer).")
    parser.add_argument("--task-num", dest="task_num", type=int, required=True,
                        help="Task number within the epic (1-based).")


def _epic_task_target(parsed) -> TargetRef:
    return TargetRef(
        kind="epic_task", epic_id=int(parsed.epic), task_num=int(parsed.task_num),
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.body_replace
# ---------------------------------------------------------------------------

EPIC_TASK_BODY_REPLACE_USAGE = (
    "yoke workflow-item epic-task body-replace --epic N --task-num N "
    "(--body TEXT | --body-file PATH | --stdin) [--session-id S] [--json]"
)


def epic_task_body_replace(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task body-replace",
        description=EPIC_TASK_BODY_REPLACE_USAGE,
    )
    _epic_target_flags(parser)
    body_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        body_group, "--body", "--body-file", dest="body",
        help_text="New task body. Use --body-file for a path.",
    )
    body_group.add_argument("--stdin", action="store_true",
                            help="Read body from stdin.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_BODY_REPLACE_USAGE)
    if parsed is None:
        return 2
    try:
        body = sys.stdin.read() if parsed.stdin else resolve_text_file(
            parsed.body, parsed.body_file, "--body-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.body_replace",
        target=_epic_task_target(parsed),
        payload={"body": body},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.split
# ---------------------------------------------------------------------------

EPIC_TASK_SPLIT_USAGE = (
    "yoke workflow-item epic-task split --epic N --task-num N "
    "--children-json JSON [--session-id S] [--json]"
)


def epic_task_split(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task split",
        description=EPIC_TASK_SPLIT_USAGE,
    )
    _epic_target_flags(parser)
    parser.add_argument("--children-json", dest="children_json", required=True,
                        help="JSON array of child task dicts (title required).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_SPLIT_USAGE)
    if parsed is None:
        return 2
    try:
        children = json.loads(parsed.children_json)
    except json.JSONDecodeError as exc:
        return usage_error(f"--children-json invalid: {exc}")
    if not isinstance(children, list):
        return usage_error("--children-json must be a JSON array")
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.split",
        target=_epic_task_target(parsed),
        payload={"children": children},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.reassign
# ---------------------------------------------------------------------------

EPIC_TASK_REASSIGN_USAGE = (
    "yoke workflow-item epic-task reassign --epic N --task-num N "
    "--new-worktree NAME [--session-id S] [--json]"
)


def epic_task_reassign(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task reassign",
        description=EPIC_TASK_REASSIGN_USAGE,
    )
    _epic_target_flags(parser)
    parser.add_argument("--new-worktree", dest="new_worktree", required=True,
                        help="Worktree branch name to reassign the task to.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REASSIGN_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.reassign",
        target=_epic_task_target(parsed),
        payload={"new_worktree": parsed.new_worktree},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.add
# ---------------------------------------------------------------------------

EPIC_TASK_ADD_USAGE = (
    "yoke workflow-item epic-task add --epic N --title TEXT "
    "[--body TEXT | --body-file PATH] [--worktree NAME] "
    "[--context-estimate TEXT] [--dependencies TEXT] [--session-id S] [--json]"
)


def epic_task_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task add",
        description=EPIC_TASK_ADD_USAGE,
    )
    parser.add_argument("--epic", type=int, required=True, help="Epic id.")
    parser.add_argument("--title", required=True, help="New task title.")
    add_text_file_pair(parser, "--body", "--body-file", dest="body",
                       help_text="Optional task body.")
    parser.add_argument("--worktree", default="", help="Worktree branch name.")
    parser.add_argument("--context-estimate", dest="context_estimate",
                        default="", help="Token/budget hint.")
    parser.add_argument("--dependencies", default="",
                        help="Comma-separated dependency task nums.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_ADD_USAGE)
    if parsed is None:
        return 2
    try:
        body = resolve_text_file(
            parsed.body, parsed.body_file, "--body-file",
        ) if (parsed.body is not None or parsed.body_file) else ""
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {
        "title": parsed.title, "body": body,
        "worktree": parsed.worktree,
        "context_estimate": parsed.context_estimate,
        "dependencies": parsed.dependencies,
    }
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.add",
        target=TargetRef(kind="epic_task", epic_id=int(parsed.epic)),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.remove
# ---------------------------------------------------------------------------

EPIC_TASK_REMOVE_USAGE = (
    "yoke workflow-item epic-task remove --epic N --task-num N "
    "[--reason TEXT] [--session-id S] [--json]"
)


def epic_task_remove(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task remove",
        description=EPIC_TASK_REMOVE_USAGE,
    )
    _epic_target_flags(parser)
    parser.add_argument("--reason", default="", help="Optional remove reason.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REMOVE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.remove",
        target=_epic_task_target(parsed),
        payload={"reason": parsed.reason},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.metadata_update
# ---------------------------------------------------------------------------

EPIC_TASK_METADATA_UPDATE_USAGE = (
    "yoke workflow-item epic-task metadata-update --epic N --task-num N "
    "--fields-json JSON [--session-id S] [--json]"
)


def epic_task_metadata_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task metadata-update",
        description=EPIC_TASK_METADATA_UPDATE_USAGE,
    )
    _epic_target_flags(parser)
    parser.add_argument("--fields-json", dest="fields_json", required=True,
                        help="JSON object of field -> value updates.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_METADATA_UPDATE_USAGE)
    if parsed is None:
        return 2
    try:
        fields = json.loads(parsed.fields_json)
    except json.JSONDecodeError as exc:
        return usage_error(f"--fields-json invalid: {exc}")
    if not isinstance(fields, dict):
        return usage_error("--fields-json must be a JSON object")
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.metadata_update",
        target=_epic_task_target(parsed),
        payload={"fields": fields},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )
