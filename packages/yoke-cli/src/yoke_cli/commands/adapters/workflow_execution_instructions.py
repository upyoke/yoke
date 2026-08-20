"""CLI adapters for operator-authored workflow execution instructions.

Also home of the shared renderer that prepends the resolved-instruction
operator block above item body / detail output.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

EXECUTION_INSTRUCTION_BLOCK_HEADER = (
    "# Workflow Execution Instructions (operator-authored — obey these)"
)


def render_execution_instruction_block(instructions: List[Dict[str, Any]]) -> str:
    """Render the labeled operator block readers prepend above item content."""
    if not instructions:
        return ""
    lines = [EXECUTION_INSTRUCTION_BLOCK_HEADER, ""]
    for instruction in instructions:
        lines.append(str(instruction.get("content") or "").rstrip())
        lines.append("")
    return "\n".join(lines) + "\n"


def _instruction_content(parsed: argparse.Namespace) -> str | None:
    if parsed.stdin:
        return sys.stdin.read()
    return parsed.content


def _dispatch(
    args: List[str],
    *,
    tokens: str,
    configure: Callable[[argparse.ArgumentParser], None] | None,
    function_id: str,
    payload: Callable[[argparse.Namespace], dict],
    human_writer: Callable[[Any, Any, Any], None] | None = None,
) -> int:
    usage = f"yoke {tokens} [--json]"
    parser = argparse.ArgumentParser(prog=f"yoke {tokens}", description=usage)
    if configure is not None:
        configure(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload(parsed),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=human_writer,
    )


def _content_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--content", help="Instruction prose.")
    parser.add_argument(
        "--stdin", action="store_true",
        help="Read the instruction prose from stdin instead of --content.",
    )


def workflow_execution_instruction_create(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction create",
        configure=_content_args,
        function_id="workflow.execution_instruction.create",
        payload=lambda parsed: {
            "content": _instruction_content(parsed) or "",
        },
    )


def _update_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("instruction_id", type=int)
    _content_args(parser)


def workflow_execution_instruction_update(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction update",
        configure=_update_args,
        function_id="workflow.execution_instruction.update",
        payload=lambda parsed: {
            "instruction_id": parsed.instruction_id,
            "content": _instruction_content(parsed) or "",
        },
    )


def _set_scope_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("instruction_id", type=int)
    parser.add_argument(
        "--all-workflows", action="store_true",
        help="Apply to every workflow, current and future.",
    )
    parser.add_argument(
        "--workflow", action="append", default=[], dest="workflows",
        help="Workflow id to bind; repeatable.",
    )
    parser.add_argument(
        "--all-projects", action="store_true",
        help="Apply to every project, current and future.",
    )
    parser.add_argument(
        "--project-id", action="append", type=int, default=[],
        dest="project_ids", help="Project id to bind; repeatable.",
    )


def workflow_execution_instruction_set_scope(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction set-scope",
        configure=_set_scope_args,
        function_id="workflow.execution_instruction.set_scope",
        payload=lambda parsed: {
            "instruction_id": parsed.instruction_id,
            "applies_to_all_workflows": parsed.all_workflows,
            "workflow_ids": parsed.workflows,
            "applies_to_all_projects": parsed.all_projects,
            "project_ids": parsed.project_ids,
        },
    )


def workflow_execution_instruction_list(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction list", configure=None,
        function_id="workflow.execution_instruction.list",
        payload=lambda _parsed: {},
    )


def _resolve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--project", required=True)


def _resolved_instructions_writer(response, stdout, stderr) -> None:
    del stderr
    if response.success:
        result = response.result or {}
        stdout.write(render_execution_instruction_block(
            result.get("execution_instructions") or []
        ))


def workflow_execution_instruction_resolve(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction resolve",
        configure=_resolve_args,
        function_id="workflow.execution_instruction.resolve",
        payload=lambda parsed: {
            "workflow": parsed.workflow,
            "project": parsed.project,
        },
        human_writer=_resolved_instructions_writer,
    )


def workflow_execution_instruction_delete(args: List[str]) -> int:
    return _dispatch(
        args, tokens="workflow execution-instruction delete",
        configure=lambda parser: parser.add_argument(
            "instruction_id", type=int,
        ),
        function_id="workflow.execution_instruction.delete",
        payload=lambda parsed: {"instruction_id": parsed.instruction_id},
    )


USAGE_BY_FUNCTION_ID = {
    "workflow.execution_instruction.create": (
        "yoke workflow execution-instruction create "
        "(--content C | --stdin) [--json]"
    ),
    "workflow.execution_instruction.update": (
        "yoke workflow execution-instruction update ID "
        "(--content C | --stdin) [--json]"
    ),
    "workflow.execution_instruction.set_scope": (
        "yoke workflow execution-instruction set-scope ID "
        "[--all-workflows] [--workflow W ...] "
        "[--all-projects] [--project-id N ...] [--json]"
    ),
    "workflow.execution_instruction.list": (
        "yoke workflow execution-instruction list [--json]"
    ),
    "workflow.execution_instruction.resolve": (
        "yoke workflow execution-instruction resolve "
        "--workflow W --project P [--json]"
    ),
    "workflow.execution_instruction.delete": (
        "yoke workflow execution-instruction delete ID [--json]"
    ),
}


__all__ = [
    "EXECUTION_INSTRUCTION_BLOCK_HEADER",
    "USAGE_BY_FUNCTION_ID",
    "render_execution_instruction_block",
    "workflow_execution_instruction_create",
    "workflow_execution_instruction_delete",
    "workflow_execution_instruction_list",
    "workflow_execution_instruction_resolve",
    "workflow_execution_instruction_set_scope",
    "workflow_execution_instruction_update",
]
