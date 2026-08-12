"""Composed deployment-flow and item-bound run adapters."""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.deployment_owner_authority import (
    https_product_plane_create_error,
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
    "yoke --env <control-plane>-db-admin deployment-runs start-for-item ITEM "
    "[--project P] [--flow F] [--target-env ENV] "
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
    parser.add_argument("flow_id")
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group, "--stages-json", "--stages-file", dest="stages_json",
    )
    group.add_argument("--stdin", action="store_true", help="Read stage JSON.")
    parser.add_argument("--description")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_FLOWS_UPDATE_STAGES_USAGE,
    )
    if parsed is None:
        return 2
    if parsed.stdin:
        stages = sys.stdin.read()
    else:
        try:
            stages = resolve_text_file(
                parsed.stages_json, parsed.stages_json_file, "--stages-file",
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
    parser.add_argument("flow_id")
    group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        group, "--description", "--description-file", dest="description",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_FLOWS_DESCRIBE_USAGE,
    )
    if parsed is None:
        return 2
    try:
        description = resolve_text_file(
            parsed.description, parsed.description_file, "--description-file",
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
            "Compose target-env resolution, run creation, item membership, "
            "and composition validation for one item. Requires the "
            "same-universe owner-only local-postgres env "
            "(`yoke --env <control-plane>-db-admin ...`); the HTTPS product "
            "plane refuses create so run rows stay writable when that plane "
            "is the deploy target."
        ),
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--flow")
    parser.add_argument("--target-env")
    parser.add_argument("--release-lineage")
    parser.add_argument("--created-by")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_START_FOR_ITEM_USAGE,
    )
    if parsed is None:
        return 2
    owner_error = https_product_plane_create_error(
        "deployment-runs start-for-item",
    )
    if owner_error is not None:
        print(f"Error: {owner_error}", file=sys.stderr)
        return 1
    payload = {
        key: value
        for key in (
            "project", "flow", "target_env", "release_lineage", "created_by",
        )
        if (value := getattr(parsed, key)) is not None
    }

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("run_id", ""), file=stdout)

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
