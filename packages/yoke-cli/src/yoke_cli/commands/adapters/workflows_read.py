"""Operator adapters for immutable workflow definitions and item pins.

Serves the registry's current immutable workflow definitions, gate placements,
and deployment flows, plus explicit current-version and item-migration actions.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.workflows_versions import (
    WORKFLOWS_CURRENT_SET_USAGE,
    WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE,
    WORKFLOWS_VERSION_GET_USAGE,
    WORKFLOWS_VERSION_LIST_USAGE,
    workflows_current_set,
    workflows_policy_defaults_publish,
    workflows_version_get,
    workflows_version_list,
)
from yoke_contracts.api.function_call import TargetRef


WORKFLOWS_DEFINITION_GET_USAGE = (
    "yoke workflows definition get [--project P] [--session-id S] [--json]"
)
WORKFLOWS_ITEM_GET_USAGE = (
    "yoke workflows item get ITEM [--project P] [--session-id S] [--json]"
)
WORKFLOWS_ITEM_MIGRATE_USAGE = (
    "yoke workflows item migrate ITEM [--version N] [--project P] "
    "[--session-id S] [--json]"
)


def workflows_definition_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows definition get",
        description=WORKFLOWS_DEFINITION_GET_USAGE,
    )
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        WORKFLOWS_DEFINITION_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(f"family|{result.get('family') or ''}", file=stdout)
        for workflow in result.get("workflows") or []:
            definition = workflow.get("definition") or {}
            stages = ",".join(
                str(stage.get("id") or "") for stage in definition.get("stages") or []
            )
            print(
                "workflow|"
                + "|".join(
                    str(value or "")
                    for value in (
                        workflow.get("id"),
                        workflow.get("current_version"),
                        workflow.get("current_version_id"),
                        workflow.get("status"),
                        stages,
                    )
                ),
                file=stdout,
            )
            for stage in definition.get("stages") or []:
                for gate in stage.get("gates") or []:
                    print(
                        f"gate|{workflow.get('id')}|{stage.get('id')}|{gate.get('id')}",
                        file=stdout,
                    )
        for gate in result.get("gate_catalog") or []:
            print(
                "catalog-gate|"
                + "|".join(
                    str(value or "")
                    for value in (
                        gate.get("id"),
                        gate.get("owner"),
                        gate.get("description"),
                    )
                ),
                file=stdout,
            )
        for flow in result.get("flows") or []:
            stage_names = ",".join(flow.get("stage_names") or [])
            print(
                "flow|"
                + "|".join(
                    "" if value is None else str(value)
                    for value in (
                        flow.get("id"),
                        flow.get("name"),
                        flow.get("target_env"),
                        flow.get("on_failure"),
                        stage_names,
                        flow.get("project"),
                    )
                ),
                file=stdout,
            )
        return None

    payload: Dict[str, Any] = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    return dispatch_and_emit(
        function_id="workflows.definition.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def workflows_item_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows item get",
        description=WORKFLOWS_ITEM_GET_USAGE,
    )
    parser.add_argument("item")
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        WORKFLOWS_ITEM_GET_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            "item-workflow|"
            + "|".join(
                str(result.get(key) or "")
                for key in (
                    "item_id",
                    "workflow_id",
                    "workflow_version",
                    "workflow_version_id",
                    "status",
                    "worktree_policy",
                )
            ),
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="workflows.item.get",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def workflows_item_migrate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows item migrate",
        description=WORKFLOWS_ITEM_MIGRATE_USAGE,
    )
    parser.add_argument("item")
    parser.add_argument("--version", type=int, default=None)
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        WORKFLOWS_ITEM_MIGRATE_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        after = result.get("after") or {}
        print(
            f"item-workflow-migrated|{str(bool(result.get('changed'))).lower()}|"
            f"{after.get('workflow_id') or ''}|"
            f"{after.get('workflow_version') or ''}|"
            f"{after.get('status') or ''}",
            file=stdout,
        )

    payload: Dict[str, Any] = {}
    if parsed.version is not None:
        payload["version"] = parsed.version
    return dispatch_and_emit(
        function_id="workflows.item.migrate",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "WORKFLOWS_CURRENT_SET_USAGE",
    "WORKFLOWS_DEFINITION_GET_USAGE",
    "WORKFLOWS_ITEM_GET_USAGE",
    "WORKFLOWS_ITEM_MIGRATE_USAGE",
    "WORKFLOWS_POLICY_DEFAULTS_PUBLISH_USAGE",
    "WORKFLOWS_VERSION_GET_USAGE",
    "WORKFLOWS_VERSION_LIST_USAGE",
    "workflows_current_set",
    "workflows_definition_get",
    "workflows_item_get",
    "workflows_item_migrate",
    "workflows_policy_defaults_publish",
    "workflows_version_get",
    "workflows_version_list",
]
