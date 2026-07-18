"""``yoke deployment-flows`` / ``yoke deployment-runs`` adapters."""

from __future__ import annotations

import argparse
import sys
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands.deployment_lineage import (
    DeploymentLineageResolutionError,
    resolve_commit_lineage,
)


DEPLOYMENT_FLOWS_GET_USAGE = (
    "yoke deployment-flows get FLOW-ID [FIELD] [--session-id S] [--json]"
)
DEPLOYMENT_FLOWS_STAGES_USAGE = (
    "yoke deployment-flows stages FLOW-ID [--session-id S] [--json]"
)
DEPLOYMENT_FLOWS_SET_STATUS_USAGE = (
    "yoke deployment-flows set-status FLOW-ID active|disabled "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_GET_USAGE = (
    "yoke deployment-runs get RUN-ID [FIELD] [--session-id S] [--json]"
)
DEPLOYMENT_RUNS_CREATE_USAGE = (
    "yoke deployment-runs create PROJECT FLOW [--target-env ENV] "
    "[--project-repo-path PATH --source-ref REF] "
    "[--created-by WHO] [--session-id S] [--json]"
)
DEPLOYMENT_RUNS_LIST_USAGE = (
    "yoke deployment-runs list [--project P] [--status STATUS] "
    "[--limit N] [--session-id S] [--json]"
)
DEPLOYMENT_RUNS_UPDATE_USAGE = (
    "yoke deployment-runs update RUN-ID FIELD VALUE [--force] "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_APPROVE_USAGE = (
    "yoke deployment-runs approve RUN-ID [--note TEXT] "
    "[--session-id S] [--json]"
)
DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE = (
    "yoke deployment-runs resolve-target-env PROJECT FLOW "
    "[--target-env ENV] [--session-id S] [--json]"
)


def _pipe(fields: list[str], row: dict[str, Any]) -> str:
    return "|".join("" if row.get(field) is None else str(row.get(field))
                    for field in fields)


def _run_target(run_id: str) -> TargetRef:
    return TargetRef(kind="workflow_run", workflow_run_id=run_id)


def deployment_flows_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows get",
        description=DEPLOYMENT_FLOWS_GET_USAGE,
    )
    parser.add_argument("flow_id")
    parser.add_argument("field", nargs="?", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_FLOWS_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if parsed.field:
            print("" if result.get("value") is None else result["value"],
                  file=stdout)
            return None
        print(_pipe(result.get("fields") or [], result.get("flow") or {}),
              file=stdout)
        return None

    return dispatch_and_emit(
        function_id="deployment_flows.get",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id, "field": parsed.field},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_flows_stages(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows stages",
        description=DEPLOYMENT_FLOWS_STAGES_USAGE,
    )
    parser.add_argument("flow_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_FLOWS_STAGES_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("stages", ""), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="deployment_flows.stages",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_flows_set_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-flows set-status",
        description=(
            "Enable or disable a deployment flow without removing its "
            "definition or historical runs."
        ),
    )
    parser.add_argument("flow_id")
    parser.add_argument("status", choices=("active", "disabled"))
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_FLOWS_SET_STATUS_USAGE
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            f"{result.get('flow_id', '')}|{result.get('status', '')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="deployment_flows.set_status",
        target=TargetRef(kind="global"),
        payload={"flow_id": parsed.flow_id, "status": parsed.status},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs get",
        description=DEPLOYMENT_RUNS_GET_USAGE,
    )
    parser.add_argument("run_id")
    parser.add_argument("field", nargs="?", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if parsed.field:
            print("" if result.get("value") is None else result["value"],
                  file=stdout)
            return None
        print(_pipe(result.get("fields") or [], result.get("run") or {}),
              file=stdout)
        return None

    return dispatch_and_emit(
        function_id="deployment_runs.get",
        target=_run_target(parsed.run_id),
        payload={"field": parsed.field},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs create",
        description=(
            "Create a zero-member environment deployment run. Item-bound "
            "delivery uses `yoke usher` / runs start-for-item instead."
        ),
    )
    parser.add_argument("project")
    parser.add_argument("flow")
    parser.add_argument("--target-env", dest="target_env", default=None)
    parser.add_argument("--created-by", dest="created_by", default="operator")
    parser.add_argument(
        "--project-repo-path",
        default=None,
        help=(
            "Git top-level used to bind release_lineage mechanically from "
            "the selected remote source ref."
        ),
    )
    parser.add_argument(
        "--source-ref",
        default="origin/main",
        help="Commit-ish to bind when --project-repo-path is supplied.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_CREATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(result.get("run_id") or "", file=stdout)
        return None

    payload = {
        "project": parsed.project,
        "flow": parsed.flow,
        "created_by": parsed.created_by,
    }
    if parsed.project_repo_path is not None:
        try:
            payload["release_lineage"] = resolve_commit_lineage(
                parsed.project_repo_path,
                parsed.source_ref,
            )
        except DeploymentLineageResolutionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    if parsed.target_env is not None:
        payload["target_env"] = parsed.target_env
    return dispatch_and_emit(
        function_id="deployment_runs.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs list",
        description=DEPLOYMENT_RUNS_LIST_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--status", default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of recent runs to return.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(_pipe(fields, row), file=stdout)
        return None

    payload = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    if parsed.status is not None:
        payload["status"] = parsed.status
    if parsed.limit is not None:
        payload["limit"] = parsed.limit
    return dispatch_and_emit(
        function_id="deployment_runs.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs update",
        description=DEPLOYMENT_RUNS_UPDATE_USAGE,
    )
    parser.add_argument("run_id")
    parser.add_argument("field")
    parser.add_argument("value")
    parser.add_argument("--force", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_UPDATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        return None

    return dispatch_and_emit(
        function_id="deployment_runs.update",
        target=_run_target(parsed.run_id),
        payload={
            "field": parsed.field,
            "value": parsed.value,
            "force": parsed.force,
        },
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_approve(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs approve",
        description=DEPLOYMENT_RUNS_APPROVE_USAGE,
    )
    parser.add_argument("run_id")
    parser.add_argument("--note", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DEPLOYMENT_RUNS_APPROVE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"Approved {result.get('run_id')}: "
            f"{result.get('approved_stage')} -> {result.get('next_stage')}",
            file=stdout,
        )
        return None

    payload = {}
    if parsed.note is not None:
        payload["note"] = parsed.note
    return dispatch_and_emit(
        function_id="deployment_runs.approve",
        target=_run_target(parsed.run_id),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_resolve_target_env(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs resolve-target-env",
        description=DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE,
    )
    parser.add_argument("project")
    parser.add_argument("flow")
    parser.add_argument("--target-env", dest="target_env", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("target_env", ""), file=stdout)
        return None

    payload = {"project": parsed.project, "flow": parsed.flow}
    if parsed.target_env is not None:
        payload["target_env"] = parsed.target_env
    return dispatch_and_emit(
        function_id="deployment_runs.resolve_target_env",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "DEPLOYMENT_FLOWS_GET_USAGE",
    "DEPLOYMENT_FLOWS_SET_STATUS_USAGE",
    "DEPLOYMENT_FLOWS_STAGES_USAGE",
    "DEPLOYMENT_RUNS_GET_USAGE",
    "DEPLOYMENT_RUNS_APPROVE_USAGE",
    "DEPLOYMENT_RUNS_LIST_USAGE",
    "DEPLOYMENT_RUNS_UPDATE_USAGE",
    "DEPLOYMENT_RUNS_RESOLVE_TARGET_ENV_USAGE",
    "deployment_flows_get",
    "deployment_flows_set_status",
    "deployment_flows_stages",
    "deployment_runs_get",
    "deployment_runs_approve",
    "deployment_runs_list",
    "deployment_runs_update",
    "deployment_runs_resolve_target_env",
]
