"""CLI adapters for operator-authored workflow execution instructions.

Also home of the shared renderer that prepends the resolved-instruction
operator block above item body / detail output.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Callable, Dict, List

from yoke_cli.commands._helpers import (
    add_full_arg,
    add_json_arg,
    add_session_arg,
    detail_of,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.read_detail import DETAIL_FULL

EXECUTION_INSTRUCTION_BLOCK_HEADER = (
    "# Workflow Execution Instructions (operator-authored — obey these)"
)
DESCRIPTOR_BLOCK_HEADER = (
    "# Workflow Execution Instructions bound to this scope (obey these; "
    "read them in full before authoring)"
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
    parser = argparse.ArgumentParser(
        prog=f"yoke {tokens}",
        description=usage
        + "\nSelect at least one delivery point; When entering stage requires a stage bucket. Creation defaults to Before creation + On every read; edits preserve omitted settings.",
    )
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


def _delivery_args(parser: argparse.ArgumentParser) -> None:
    for flag, label in (
        ("before-creation", "Before creation"),
        ("on-every-read", "On every read"),
        ("when-entering-stage", "When entering stage"),
    ):
        parser.add_argument(
            f"--{flag}",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=f"Enable/disable {label}; omitted settings are preserved.",
        )
    parser.add_argument(
        "--stage-bucket",
        action="append",
        dest="stage_buckets",
        help="Stage target: idea, planning, refined, implementing, reviewing, implemented, release; repeatable.",
    )
    parser.add_argument(
        "--clear-stage-buckets",
        action="store_true",
        help="Clear targets (disable When entering stage in the same edit).",
    )


def _delivery_payload(parsed: argparse.Namespace) -> dict:
    fields = (
        "before_creation",
        "on_every_read",
        "when_entering_stage",
        "stage_buckets",
    )
    result = {
        key: getattr(parsed, key) for key in fields if getattr(parsed, key) is not None
    }
    if parsed.clear_stage_buckets:
        result["stage_buckets"] = []
    return result


def _content_args(parser: argparse.ArgumentParser) -> None:
    _delivery_args(parser)
    parser.add_argument("--content", help="Instruction prose.")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the instruction prose from stdin instead of --content.",
    )


def workflow_execution_instruction_create(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction create",
        configure=_content_args,
        function_id="workflow.execution_instruction.create",
        payload=lambda parsed: {
            "content": _instruction_content(parsed) or "",
            **_delivery_payload(parsed),
        },
    )


def _update_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("instruction_id", type=int)
    _content_args(parser)


def workflow_execution_instruction_update(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction update",
        configure=_update_args,
        function_id="workflow.execution_instruction.update",
        payload=lambda parsed: {
            "instruction_id": parsed.instruction_id,
            "content": _instruction_content(parsed) or "",
            **_delivery_payload(parsed),
        },
    )


def _set_scope_args(parser: argparse.ArgumentParser) -> None:
    _delivery_args(parser)
    parser.add_argument("instruction_id", type=int)
    parser.add_argument(
        "--all-workflows",
        action="store_true",
        help="Apply to every workflow, current and future.",
    )
    parser.add_argument(
        "--workflow",
        action="append",
        default=[],
        dest="workflows",
        help="Workflow id to bind; repeatable.",
    )
    parser.add_argument(
        "--all-projects",
        action="store_true",
        help="Apply to every project, current and future.",
    )
    parser.add_argument(
        "--project-id",
        action="append",
        type=int,
        default=[],
        dest="project_ids",
        help="Project id to bind; repeatable.",
    )


def workflow_execution_instruction_set_scope(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction set-scope",
        configure=_set_scope_args,
        function_id="workflow.execution_instruction.set_scope",
        payload=lambda parsed: {
            "instruction_id": parsed.instruction_id,
            "applies_to_all_workflows": parsed.all_workflows,
            "workflow_ids": parsed.workflows,
            "applies_to_all_projects": parsed.all_projects,
            "project_ids": parsed.project_ids,
            **_delivery_payload(parsed),
        },
    )


def workflow_execution_instruction_list(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction list",
        configure=None,
        function_id="workflow.execution_instruction.list",
        payload=lambda _parsed: {},
    )


def _resolve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--delivery-point",
        default="before_creation",
        help="before_creation (default), on_every_read, or when_entering_stage.",
    )
    parser.add_argument(
        "--stage-bucket", help="Live or entered bucket for stage delivery."
    )
    add_full_arg(parser, "the instruction prose a filer must read and obey")


def render_instruction_descriptors(descriptors: List[Dict[str, Any]]) -> str:
    """List what binds this scope, and the command that serves the prose."""
    if not descriptors:
        return "No operator execution instructions apply to this scope.\n"
    lines = [DESCRIPTOR_BLOCK_HEADER, ""]
    for descriptor in descriptors:
        lines.append(f"  {descriptor.get('id')}  {descriptor.get('title') or ''}")
    lines.extend(["", f"Read them in full: {descriptors[0].get('read') or ''}", ""])
    return "\n".join(lines)


def _resolved_instructions_writer(response, stdout, stderr) -> None:
    del stderr
    if not response.success:
        return
    result = response.result or {}
    instructions = result.get("execution_instructions") or []
    if result.get("detail") == DETAIL_FULL:
        stdout.write(render_execution_instruction_block(instructions))
        return
    stdout.write(render_instruction_descriptors(instructions))


def workflow_execution_instruction_resolve(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction resolve",
        configure=_resolve_args,
        function_id="workflow.execution_instruction.resolve",
        payload=lambda parsed: {
            "workflow": parsed.workflow,
            "project": parsed.project,
            "detail": detail_of(parsed),
            **(
                {"delivery_point": parsed.delivery_point}
                if parsed.delivery_point != "before_creation"
                else {}
            ),
            **({"stage_bucket": parsed.stage_bucket} if parsed.stage_bucket else {}),
        },
        human_writer=_resolved_instructions_writer,
    )


def workflow_execution_instruction_delete(args: List[str]) -> int:
    return _dispatch(
        args,
        tokens="workflow execution-instruction delete",
        configure=lambda parser: parser.add_argument(
            "instruction_id",
            type=int,
        ),
        function_id="workflow.execution_instruction.delete",
        payload=lambda parsed: {"instruction_id": parsed.instruction_id},
    )


USAGE_BY_FUNCTION_ID = {
    "workflow.execution_instruction.create": (
        "yoke workflow execution-instruction create (--content C | --stdin) [--json]"
    ),
    "workflow.execution_instruction.update": (
        "yoke workflow execution-instruction update ID (--content C | --stdin) [--json]"
    ),
    "workflow.execution_instruction.set_scope": (
        "yoke workflow execution-instruction set-scope ID "
        "[--all-workflows] [--workflow W ...] "
        "[--all-projects] [--project-id N ...] [--before-creation | --no-before-creation] "
        "[--on-every-read | --no-on-every-read] [--when-entering-stage | --no-when-entering-stage] "
        "[--stage-bucket B ... | --clear-stage-buckets] [--json]"
    ),
    "workflow.execution_instruction.list": (
        "yoke workflow execution-instruction list [--json]"
    ),
    "workflow.execution_instruction.resolve": (
        "yoke workflow execution-instruction resolve "
        "--workflow W --project P [--delivery-point POINT] [--stage-bucket B] [--full] [--json]"
    ),
    "workflow.execution_instruction.delete": (
        "yoke workflow execution-instruction delete ID [--json]"
    ),
}


def write_transition_instructions(response, stdout, stderr) -> None:
    """Serve entry instructions in full; retain the transition receipt."""
    import json

    del stderr
    result = dict(response.result or {})
    stdout.write(
        render_execution_instruction_block(
            result.pop("execution_instructions", []) or []
        )
    )
    print(json.dumps(result, sort_keys=True), file=stdout)


def write_item_content(response, stdout, stderr) -> None:
    """Render read instructions before a section or Progress Log."""
    del stderr
    if not response.success:
        return
    result = response.result or {}
    stdout.write(
        render_execution_instruction_block(result.get("execution_instructions") or [])
    )
    text = str(result.get("content") or "")
    stdout.write(text)
    if text and not text.endswith("\n"):
        stdout.write("\n")
