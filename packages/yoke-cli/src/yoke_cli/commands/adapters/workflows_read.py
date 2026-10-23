"""Operator adapters for immutable workflow definitions and item pins.

Serves the registry's current immutable workflow definitions, gate placements,
and deployment flows, plus explicit current-version and item-migration actions.
"""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

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
    "yoke workflows item migrate ITEM [--version N] [--preview] [--project P] "
    "[--session-id S] [--json]"
)
WORKFLOWS_ITEM_MIGRATE_DESCRIPTION = (
    "Requires a live steering seat covering the item's project or document. "
    "Acquire it with yoke claims steering acquire --project P --reason TEXT, "
    "or route via yoke say --steering."
)


def workflows_definition_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke workflows definition get",
        usage=WORKFLOWS_DEFINITION_GET_USAGE,
    )
    parser.add_argument("--project", default=None, help="Project to read from.")
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
        write_human(response.result or {}, stdout)

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
        usage=WORKFLOWS_ITEM_GET_USAGE,
    )
    parser.add_argument("item", help="Item to read, as PREFIX-N.")
    parser.add_argument("--project", default=None, help="Project that owns the item.")
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
        write_human(response.result or {}, stdout)

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
        usage=WORKFLOWS_ITEM_MIGRATE_USAGE,
        description=WORKFLOWS_ITEM_MIGRATE_DESCRIPTION,
    )
    parser.add_argument("item", help="Item to migrate, as PREFIX-N.")
    parser.add_argument(
        "--version",
        type=int,
        default=None,
        help="Version to move to; default: current.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Return migration conflicts without changing the item pin.",
    )
    parser.add_argument("--project", default=None, help="Project that owns the item.")
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
        write_human(response.result or {}, stdout)

    payload: Dict[str, Any] = {}
    if parsed.version is not None:
        payload["version"] = parsed.version
    if parsed.preview:
        payload["preview"] = True
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
