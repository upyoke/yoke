"""Generated-task scope CLI adapters."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


def _target(parsed, *, task: bool = False) -> TargetRef:
    return TargetRef(
        kind="epic_task",
        epic_id=int(parsed.epic),
        task_num=int(parsed.task_num) if task else None,
    )


def _write_message(response, stdout, stderr) -> None:
    stdout.write(f"{(response.result or {}).get('message', '')}\n")


def _write_scope_repair(response, stdout, stderr) -> None:
    result = response.result or {}
    diagnostics = result.get("diagnostics", [])
    stdout.write(f"{result.get('message', '')}\n")
    epic = result.get("epic_public_ref")
    deferred = []
    for diagnostic in diagnostics:
        stdout.write(f"- {diagnostic}\n")
        if not diagnostic.endswith("scope=legacy_deferred"):
            continue
        task_num = diagnostic.split(" task=", 1)[1].split(" ", 1)[0]
        deferred.append(task_num)
        if epic:
            stdout.write(
                "  Repair: run `file-add` or `scope-no-files` for "
                f"--epic {epic} --task-num {task_num}.\n"
            )
    if deferred and epic:
        stdout.write(f"Then run `scope-finalize --epic {epic}`.\n")


def _run(
    args: List[str],
    *,
    name: str,
    function_id: str,
    usage: str,
    task: bool = False,
    tenant: bool = False,
) -> int:
    parser = argparse.ArgumentParser(
        prog=f"yoke workflow-item epic-task {name}",
        description=usage,
    )
    parser.add_argument("--epic", type=int, required=True, help="Epic id.")
    if task:
        parser.add_argument("--task-num", type=int, required=True)
    if tenant:
        parser.add_argument("--tenant-id", default="current")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"tenant_id": parsed.tenant_id} if tenant else {}
    writer = _write_scope_repair if tenant else _write_message
    return dispatch_and_emit(
        function_id=function_id,
        target=_target(parsed, task=task),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
    )


EPIC_TASK_SCOPE_NO_FILES_USAGE = (
    "yoke workflow-item epic-task scope-no-files --epic N --task-num N "
    "[--session-id S] [--json]"
)
EPIC_TASK_SCOPE_FINALIZE_USAGE = (
    "yoke workflow-item epic-task scope-finalize --epic N "
    "[--session-id S] [--json]"
)
EPIC_TASK_SCOPE_REOPEN_USAGE = (
    "yoke workflow-item epic-task scope-reopen --epic N "
    "[--session-id S] [--json]"
)
EPIC_TASK_SCOPE_REPAIR_LEGACY_USAGE = (
    "yoke workflow-item epic-task scope-repair-legacy --epic N "
    "[--tenant-id ID] [--session-id S] [--json]"
)


def epic_task_scope_no_files(args: List[str]) -> int:
    return _run(
        args,
        name="scope-no-files",
        function_id="workflow_item.epic_task.scope_no_files",
        usage=EPIC_TASK_SCOPE_NO_FILES_USAGE,
        task=True,
    )


def epic_task_scope_finalize(args: List[str]) -> int:
    return _run(
        args,
        name="scope-finalize",
        function_id="workflow_item.epic_task.scope_finalize",
        usage=EPIC_TASK_SCOPE_FINALIZE_USAGE,
    )


def epic_task_scope_reopen(args: List[str]) -> int:
    return _run(
        args,
        name="scope-reopen",
        function_id="workflow_item.epic_task.scope_reopen",
        usage=EPIC_TASK_SCOPE_REOPEN_USAGE,
    )


def epic_task_scope_repair_legacy(args: List[str]) -> int:
    return _run(
        args,
        name="scope-repair-legacy",
        function_id="workflow_item.epic_task.scope_repair_legacy",
        usage=EPIC_TASK_SCOPE_REPAIR_LEGACY_USAGE,
        tenant=True,
    )


__all__ = [
    "EPIC_TASK_SCOPE_FINALIZE_USAGE",
    "EPIC_TASK_SCOPE_NO_FILES_USAGE",
    "EPIC_TASK_SCOPE_REOPEN_USAGE",
    "EPIC_TASK_SCOPE_REPAIR_LEGACY_USAGE",
    "epic_task_scope_finalize",
    "epic_task_scope_no_files",
    "epic_task_scope_reopen",
    "epic_task_scope_repair_legacy",
]
