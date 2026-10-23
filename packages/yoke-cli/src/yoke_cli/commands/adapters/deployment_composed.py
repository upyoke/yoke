"""Composed deployment-flow and item-bound run adapters."""

from __future__ import annotations

import argparse
import shlex
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    run_id_receipt,
    usage_error,
)
from yoke_cli.commands.adapters.deployment_execution_authority import (
    creation_connection_error,
)
from yoke_cli.commands.text_file import add_text_file_pair, resolve_text_file
from yoke_contracts.api.function_call import TargetRef


DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE = (
    "yoke deployment-flows update-stages FLOW-ID "
    "(--stages-json JSON | --stages-file PATH | --stdin) "
    "[--description TEXT] [--session-id S] [--json]"
)
DEPLOYMENT_FLOWS_DESCRIBE_USAGE = (
    "yoke deployment-flows describe FLOW-ID "
    "(--description TEXT | --description-file PATH) "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE = (
    "yoke deployment-runs start-for-item ITEM "
    "[--project P] [--flow F] [--environment ENV] "
    "[--release-lineage LINEAGE] [--created-by WHO] "
    "[--session-id S] [--json]"
)


def deployment_flows_update_stages(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows update-stages",
        description=(
            "Replace a flow's stages while preserving the immutable-history "
            "guard once a deployment run references it."
        ),
    )
    parser.add_argument("flow_id", help="Deployment flow to update.")
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group,
        "--stages-json",
        "--stages-file",
        dest="stages_json",
    )
    group.add_argument("--stdin", action="store_true", help="Read stage JSON.")
    parser.add_argument("--description", help="New description for the flow.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.stdin:
        stages = sys.stdin.read()
    else:
        try:
            stages = resolve_text_file(
                parsed.stages_json,
                parsed.stages_json_file,
                "--stages-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("message", ""), file=stdout)

    payload = {"flow_id": parsed.flow_id, "stages": stages}
    if parsed.description is not None:
        payload["description"] = parsed.description
    return dispatch_and_emit(
        function_id="deployment_flows.update_stages",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_flows_describe(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows describe",
        description=(
            "Rewrite a flow's description. Stages stay untouched, so this "
            "works on flows whose definition is frozen by run history."
        ),
    )
    parser.add_argument("flow_id", help="Deployment flow to describe.")
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group,
        "--description",
        "--description-file",
        dest="description",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEPLOYMENT_FLOWS_DESCRIBE_USAGE,
    )
    if parsed is None:
        return 2
    try:
        description = resolve_text_file(
            parsed.description,
            parsed.description_file,
            "--description-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_flows.describe",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id, "description": description},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_start_for_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs start-for-item",
        description=(
            "Open a delivery run for one named item on the selected "
            "control-plane transport. Creation, any takeover of an older run "
            "on the target, the item's enrollment and composition validation "
            "commit together or not at all; start revalidates before "
            "dispatch. While a live steering seat covers the project only "
            "its holder, or an older run's creator, may take that run over "
            "(takeover_reserved_for_steering); other sessions report the "
            "landing to steering. A self-deploy target needs this machine's "
            "paired database connection to drive it, so creation refuses "
            "without one."
        ),
    )
    parser.add_argument("item", help="Item to deliver, as PREFIX-N.")
    parser.add_argument("--project", help="Project that owns the item.")
    parser.add_argument("--flow", help="Flow to run; default: the item's own flow.")
    parser.add_argument(
        "--environment", help="Target environment; default: the flow's."
    )
    parser.add_argument(
        "--release-lineage",
        help="Commit to deliver; default for stage: the gate branch head.",
    )
    parser.add_argument("--created-by", help="Who opened the run; default: operator.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
    )
    if parsed is None:
        return 2
    if refusal := creation_connection_error(
        f"start-for-item {shlex.join(args)}",
        project=parsed.project,
        flow=parsed.flow,
        environment=parsed.environment,
        item=parsed.item,
    ):
        print(f"error: {refusal}", file=sys.stderr)
        return 2
    payload = {
        key: value
        for key in (
            "project",
            "flow",
            "environment",
            "release_lineage",
            "created_by",
        )
        if (value := getattr(parsed, key)) is not None
    }

    def _human_writer(response, stdout, stderr) -> None:
        run_id_receipt(response, stdout, stderr)
        # Composition may have completed itself from the pinned candidate.
        # Naming the run alone would hide members the operator never chose.
        message = str((response.result or {}).get("validation_message") or "")
        if message and message != "OK":
            print(message, file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.start_for_item",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "deployment_flows_update_stages",
    "deployment_runs_start_for_item",
]
