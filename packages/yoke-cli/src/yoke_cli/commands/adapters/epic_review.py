"""``yoke workflow-item epic-task review-* ...`` flag adapters.

Four adapters covering the ``workflow_item.epic_task.review_*`` family
(the tester-subagent review hot path): ``review_seed``,
``review_insert``, ``review_get``, ``review_list``. Sibling of
:mod:`yoke_cli.commands.adapters.epic_task`; the remaining epic-task shapes
live in :mod:`yoke_cli.commands.adapters.epic_state`.

All entries target ``kind="epic_task"`` with ``(epic_id, task_num)``.
``USAGE_BY_FUNCTION_ID`` feeds the facade's ``ADAPTER_USAGE`` map.
"""

from __future__ import annotations

import argparse
import sys
from typing import Dict, List

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
    "epic_task_review_seed", "epic_task_review_insert",
    "epic_task_review_get", "epic_task_review_list",
    "EPIC_TASK_REVIEW_SEED_USAGE", "EPIC_TASK_REVIEW_INSERT_USAGE",
    "EPIC_TASK_REVIEW_GET_USAGE", "EPIC_TASK_REVIEW_LIST_USAGE",
    "USAGE_BY_FUNCTION_ID",
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


def _message_writer(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('message', '')}\n")


# ---------------------------------------------------------------------------
# workflow_item.epic_task.review_seed
# ---------------------------------------------------------------------------

EPIC_TASK_REVIEW_SEED_USAGE = (
    "yoke workflow-item epic-task review-seed --epic N --task-num N "
    "[--session-id S] [--json]"
)


def epic_task_review_seed(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task review-seed",
        description=(
            "Idempotently seed the blocking implementation-review "
            "requirement for one epic task (auto-advances implementing -> "
            "reviewing-implementation). Example: yoke workflow-item "
            "epic-task review-seed --epic 1704 --task-num 3"
        ),
    )
    _epic_target_flags(parser)
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REVIEW_SEED_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.review_seed",
        target=_epic_task_target(parsed),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_message_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.review_insert
# ---------------------------------------------------------------------------

EPIC_TASK_REVIEW_INSERT_USAGE = (
    "yoke workflow-item epic-task review-insert --epic N --task-num N "
    "--verdict pass|fail (--body TEXT | --body-file PATH | --stdin) "
    "[--session-id S] [--json]"
)


def epic_task_review_insert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task review-insert",
        description=(
            "Record a review verdict for one epic task (a passing verdict "
            "auto-advances reviewing-implementation -> "
            "reviewed-implementation). Example: yoke workflow-item "
            "epic-task review-insert --epic 1704 --task-num 3 "
            "--verdict pass --body-file /tmp/yoke-review.3.md"
        ),
    )
    _epic_target_flags(parser)
    parser.add_argument("--verdict", required=True, type=str.lower,
                        choices=["pass", "fail"],
                        help="Review verdict (case-insensitive).")
    body_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        body_group, "--body", "--body-file", dest="body",
        help_text="Review body (rationale, evidence, failing-test traces).",
    )
    body_group.add_argument("--stdin", action="store_true",
                            help="Read body from stdin.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REVIEW_INSERT_USAGE)
    if parsed is None:
        return 2
    try:
        body = sys.stdin.read() if parsed.stdin else resolve_text_file(
            parsed.body, parsed.body_file, "--body-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="workflow_item.epic_task.review_insert",
        target=_epic_task_target(parsed),
        payload={"verdict": parsed.verdict, "body": body},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_message_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.review_get
# ---------------------------------------------------------------------------

EPIC_TASK_REVIEW_GET_USAGE = (
    "yoke workflow-item epic-task review-get --epic N --task-num N "
    "[--session-id S] [--json]"
)


def epic_task_review_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task review-get",
        description=(
            "Read the most recent review for one epic task. Prints one "
            "pipe row: id|epic_id|task_num|verdict|body|created_at. "
            "Example: yoke workflow-item epic-task review-get "
            "--epic 1704 --task-num 3"
        ),
    )
    _epic_target_flags(parser)
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REVIEW_GET_USAGE)
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        stdout.write(f"{(response.result or {}).get('review', '')}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.review_get",
        target=_epic_task_target(parsed),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.review_list
# ---------------------------------------------------------------------------

EPIC_TASK_REVIEW_LIST_USAGE = (
    "yoke workflow-item epic-task review-list --epic N --task-num N "
    "[--limit N] [--session-id S] [--json]"
)


def epic_task_review_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task review-list",
        description=(
            "List review history for one epic task, newest first. Prints "
            "pipe rows: id|epic_id|task_num|verdict|body|created_at "
            "(empty when no reviews exist). Example: yoke workflow-item "
            "epic-task review-list --epic 1704 --task-num 3 --limit 5"
        ),
    )
    _epic_target_flags(parser)
    parser.add_argument("--limit", type=int, default=0,
                        help="Optional max number of reviews (0 = all).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_REVIEW_LIST_USAGE)
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        reviews = (response.result or {}).get("reviews", "")
        if reviews:
            stdout.write(f"{reviews}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.review_list",
        target=_epic_task_target(parsed),
        payload={"limit": int(parsed.limit)},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "workflow_item.epic_task.review_seed": EPIC_TASK_REVIEW_SEED_USAGE,
    "workflow_item.epic_task.review_insert": EPIC_TASK_REVIEW_INSERT_USAGE,
    "workflow_item.epic_task.review_get": EPIC_TASK_REVIEW_GET_USAGE,
    "workflow_item.epic_task.review_list": EPIC_TASK_REVIEW_LIST_USAGE,
}
