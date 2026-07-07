"""``yoke workflow-item epic-task ...`` state/read flag adapters.

Four adapters covering the remaining ``workflow_item.epic_task.*``
shapes: ``body_get``, ``update_status``, ``simulation_upsert``,
``submission_receipt_get``. Sibling of
:mod:`yoke_cli.commands.adapters.epic_task`; the review family lives in
:mod:`yoke_cli.commands.adapters.epic_review`.

``USAGE_BY_FUNCTION_ID`` feeds the facade's ``ADAPTER_USAGE`` map.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
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
    "epic_task_body_get", "epic_task_update_status",
    "epic_task_simulation_upsert", "epic_task_submission_receipt_get",
    "EPIC_TASK_BODY_GET_USAGE", "EPIC_TASK_UPDATE_STATUS_USAGE",
    "EPIC_TASK_SIMULATION_UPSERT_USAGE",
    "EPIC_TASK_SUBMISSION_RECEIPT_GET_USAGE",
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


# ---------------------------------------------------------------------------
# workflow_item.epic_task.body_get
# ---------------------------------------------------------------------------

EPIC_TASK_BODY_GET_USAGE = (
    "yoke workflow-item epic-task body-get --epic N --task-num N "
    "[--output-file PATH] [--session-id S] [--json]"
)


def epic_task_body_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task body-get",
        description=(
            "Read one epic task body verbatim. --output-file writes the "
            "body to a path instead of stdout (for chained file reads). "
            "Example: yoke workflow-item epic-task body-get "
            "--epic 1704 --task-num 3"
        ),
    )
    _epic_target_flags(parser)
    parser.add_argument("--output-file", dest="output_file", default=None,
                        help="Write the body to this path instead of stdout.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_BODY_GET_USAGE)
    if parsed is None:
        return 2
    if parsed.output_file and parsed.json_mode:
        return usage_error("--output-file and --json are mutually exclusive")

    def _writer(response, stdout, stderr) -> None:
        body = (response.result or {}).get("body", "")
        if parsed.output_file:
            Path(parsed.output_file).write_text(body, encoding="utf-8")
        else:
            stdout.write(f"{body}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.body_get",
        target=_epic_task_target(parsed),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.update_status
# ---------------------------------------------------------------------------

EPIC_TASK_UPDATE_STATUS_USAGE = (
    "yoke workflow-item epic-task update-status --epic N --task-num N "
    "--status STATUS [--session-id S] [--json]"
)


def epic_task_update_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task update-status",
        description=(
            "Write a non-terminal lifecycle status on one epic task "
            "(syncs the GitHub label). Terminal success statuses are "
            "pipeline-owned and refused here. Example: yoke "
            "workflow-item epic-task update-status --epic 1704 "
            "--task-num 3 --status planned"
        ),
    )
    _epic_target_flags(parser)
    parser.add_argument("--status", required=True,
                        help="Target task status (lifecycle vocabulary).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_UPDATE_STATUS_USAGE)
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        stdout.write(f"{(response.result or {}).get('message', '')}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.update_status",
        target=_epic_task_target(parsed),
        payload={"status": parsed.status},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.simulation_upsert
# ---------------------------------------------------------------------------

EPIC_TASK_SIMULATION_UPSERT_USAGE = (
    "yoke workflow-item epic-task simulation-upsert --epic N --phase P "
    "(--body TEXT | --body-file PATH | --stdin) [--session-id S] [--json]"
)


def epic_task_simulation_upsert(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task simulation-upsert",
        description=(
            "Persist a Simulator report for an epic phase as qa rows "
            "(epic-level: no --task-num; CLEAN / GAPS FOUND is parsed "
            "from the body; re-upserting a phase replaces prior runs). "
            "Example: yoke workflow-item epic-task simulation-upsert "
            "--epic 1704 --phase plan --body-file /tmp/sim-report.md"
        ),
    )
    parser.add_argument("--epic", type=int, required=True,
                        help="Epic id (bare integer).")
    parser.add_argument("--phase", required=True,
                        help="Simulation phase (e.g. plan, integration).")
    body_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        body_group, "--body", "--body-file", dest="body",
        help_text="Simulation report body (Markdown).",
    )
    body_group.add_argument("--stdin", action="store_true",
                            help="Read body from stdin.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPIC_TASK_SIMULATION_UPSERT_USAGE)
    if parsed is None:
        return 2
    try:
        body = sys.stdin.read() if parsed.stdin else resolve_text_file(
            parsed.body, parsed.body_file, "--body-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))

    def _writer(response, stdout, stderr) -> None:
        stdout.write(f"{(response.result or {}).get('message', '')}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.simulation_upsert",
        target=TargetRef(kind="epic_task", epic_id=int(parsed.epic)),
        payload={"phase": parsed.phase, "body": body},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


# ---------------------------------------------------------------------------
# workflow_item.epic_task.submission_receipt_get
# ---------------------------------------------------------------------------

EPIC_TASK_SUBMISSION_RECEIPT_GET_USAGE = (
    "yoke workflow-item epic-task submission-receipt-get --epic N "
    "--task-num N [--after-note-count N] [--session-id S] [--json]"
)


def epic_task_submission_receipt_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflow-item epic-task submission-receipt-get",
        description=(
            "Read + validate the latest Engineer submission receipt from "
            "epic_progress_notes. Prints "
            "PASS|epic|task|note|commit|ts|fields on success; fails with "
            "target_not_found (no receipt) or receipt_invalid (failing "
            "fields). Example: yoke workflow-item epic-task "
            "submission-receipt-get --epic 1704 --task-num 3 "
            "--after-note-count 2"
        ),
    )
    _epic_target_flags(parser)
    parser.add_argument("--after-note-count", dest="after_note_count",
                        type=int, default=0,
                        help="Only consider notes after this note_num "
                             "watermark (default 0 = all).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, EPIC_TASK_SUBMISSION_RECEIPT_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _writer(response, stdout, stderr) -> None:
        stdout.write(f"{(response.result or {}).get('receipt', '')}\n")

    return dispatch_and_emit(
        function_id="workflow_item.epic_task.submission_receipt_get",
        target=_epic_task_target(parsed),
        payload={"after_note_count": int(parsed.after_note_count)},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_writer,
    )


USAGE_BY_FUNCTION_ID: Dict[str, str] = {
    "workflow_item.epic_task.body_get": EPIC_TASK_BODY_GET_USAGE,
    "workflow_item.epic_task.update_status": EPIC_TASK_UPDATE_STATUS_USAGE,
    "workflow_item.epic_task.simulation_upsert":
        EPIC_TASK_SIMULATION_UPSERT_USAGE,
    "workflow_item.epic_task.submission_receipt_get":
        EPIC_TASK_SUBMISSION_RECEIPT_GET_USAGE,
}
