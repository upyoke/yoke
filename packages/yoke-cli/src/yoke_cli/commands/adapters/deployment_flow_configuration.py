"""CLI adapters for complete deployment-flow definition configuration."""

from __future__ import annotations

import argparse
import sys
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef


UPDATE_USAGE = (
    "yoke deployment-flows update FLOW-ID [--name NAME] [--description TEXT] "
    "[--stages-json JSON | --stages-file PATH | --stdin] "
    "[--on-failure halt|continue] [--target-tier persistent|ephemeral|none] "
    "[--environment ENV] [--done-description TEXT] "
    "[--takes-delivery-custody true|false] [--session-id S] [--json]"
)
REORDER_USAGE = (
    "yoke deployment-flows reorder FLOW-ID --order NAME,NAME [--session-id S] [--json]"
)
VALIDATE_USAGE = (
    "yoke deployment-flows validate --project P "
    "(--stages-json JSON | --stages-file PATH | --stdin) "
    "[--target-tier persistent|ephemeral] [--environment ENV] "
    "[--status active|disabled] [--session-id S] [--json]"
)
VERSION_USAGE = (
    "yoke deployment-flows version SOURCE-FLOW NEW-FLOW --name NAME "
    "[definition options] [--status active|disabled] [--session-id S] [--json]"
)

_UNSET = "__deployment_flow_unset__"


def _add_stage_source(parser: argparse.ArgumentParser, *, required: bool) -> None:
    group = parser.add_mutually_exclusive_group(required=required)
    add_text_file_pair(group, "--stages-json", "--stages-file", dest="stages_json")
    group.add_argument("--stdin", action="store_true", help="Read stage JSON.")


def _read_stages(parsed: argparse.Namespace) -> str | None:
    if getattr(parsed, "stdin", False):
        return sys.stdin.read()
    inline = getattr(parsed, "stages_json", None)
    path = getattr(parsed, "stages_json_file", None)
    if inline is None and path is None:
        return None
    return resolve_text_file(inline, path, "--stages-file")


def _add_definition_options(
    parser: argparse.ArgumentParser,
    *,
    stages_required: bool,
    include_name: bool,
) -> None:
    if include_name:
        parser.add_argument("--name", required=True)
    else:
        parser.add_argument("--name", default=None)
    parser.add_argument("--description", default=None)
    _add_stage_source(parser, required=stages_required)
    parser.add_argument("--on-failure", choices=("halt", "continue"), default=None)
    parser.add_argument(
        "--target-tier",
        choices=("persistent", "ephemeral", "none"),
        default=_UNSET,
    )
    parser.add_argument("--environment", default=None)
    parser.add_argument("--done-description", default=None)
    parser.add_argument(
        "--takes-delivery-custody",
        choices=("true", "false"),
        default=None,
    )


def _changes(parsed: argparse.Namespace) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for field in ("name", "description", "on_failure", "done_description"):
        value = getattr(parsed, field, None)
        if value is not None:
            changes[field] = value
    stages = _read_stages(parsed)
    if stages is not None:
        changes["stages"] = stages
    target_tier = getattr(parsed, "target_tier", _UNSET)
    if target_tier != _UNSET:
        changes["target_tier"] = None if target_tier == "none" else target_tier
        if target_tier == "none":
            changes["environment"] = None
    if parsed.environment is not None:
        changes["environment"] = parsed.environment
    custody = getattr(parsed, "takes_delivery_custody", None)
    if custody is not None:
        changes["takes_delivery_custody"] = custody == "true"
    return changes


def _flow_writer(response, stdout, stderr) -> None:
    del stderr
    flow = (response.result or {}).get("flow") or {}
    print(
        "|".join(
            str(flow.get(key) or "")
            for key in ("id", "definition_schema_version", "status")
        ),
        file=stdout,
    )


def deployment_flows_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke deployment-flows update")
    parser.add_argument("flow_id")
    _add_definition_options(parser, stages_required=False, include_name=False)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, UPDATE_USAGE)
    if parsed is None:
        return 2
    try:
        changes = _changes(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    if not changes:
        return usage_error("at least one definition option is required")
    return dispatch_and_emit(
        function_id="deployment_flows.update",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id, "changes": changes},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_flow_writer,
    )


def deployment_flows_reorder(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke deployment-flows reorder")
    parser.add_argument("flow_id")
    parser.add_argument("--order", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, REORDER_USAGE)
    if parsed is None:
        return 2
    order = [name.strip() for name in parsed.order.split(",") if name.strip()]
    if not order:
        return usage_error("--order must name at least one stage")
    return dispatch_and_emit(
        function_id="deployment_flows.reorder",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id, "order": order},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_flow_writer,
    )


def deployment_flows_validate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke deployment-flows validate")
    parser.add_argument("--project", required=True)
    _add_stage_source(parser, required=True)
    parser.add_argument("--target-tier", choices=("persistent", "ephemeral"))
    parser.add_argument("--environment")
    parser.add_argument("--status", choices=("active", "disabled"), default="disabled")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VALIDATE_USAGE)
    if parsed is None:
        return 2
    try:
        stages = _read_stages(parsed)
    except ValueError as exc:
        return usage_error(str(exc))

    def writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            f"valid|schema={result.get('definition_schema_version')}|"
            f"execution_supported={str(bool(result.get('execution_supported'))).lower()}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="deployment_flows.validate",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload={
            "project": parsed.project,
            "stages": stages,
            "target_tier": parsed.target_tier,
            "environment": parsed.environment,
            "status": parsed.status,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=writer,
    )


def deployment_flows_version(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke deployment-flows version")
    parser.add_argument("source_flow_id")
    parser.add_argument("new_flow_id")
    _add_definition_options(parser, stages_required=False, include_name=True)
    parser.add_argument("--status", choices=("active", "disabled"), default="disabled")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VERSION_USAGE)
    if parsed is None:
        return 2
    try:
        changes = _changes(parsed)
    except ValueError as exc:
        return usage_error(str(exc))
    changes.pop("name", None)
    return dispatch_and_emit(
        function_id="deployment_flows.version",
        target=TargetRef(kind="global"),
        payload={
            "source_flow_id": parsed.source_flow_id,
            "new_flow_id": parsed.new_flow_id,
            "name": parsed.name,
            "changes": changes,
            "status": parsed.status,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_flow_writer,
    )


__all__ = [
    "REORDER_USAGE",
    "UPDATE_USAGE",
    "VALIDATE_USAGE",
    "VERSION_USAGE",
    "deployment_flows_reorder",
    "deployment_flows_update",
    "deployment_flows_validate",
    "deployment_flows_version",
]
