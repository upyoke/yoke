"""``yoke ephemeral-env`` adapters."""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


EPHEMERAL_ENV_UPDATE_USAGE = (
    "yoke ephemeral-env update ENV-ID FIELD VALUE [--session-id S] [--json]"
)
EPHEMERAL_ENV_CREATE_USAGE = (
    "yoke ephemeral-env create PROJECT BRANCH [--item PREFIX-N] "
    "[--workflow-run-id ID] [--github-ref REF] [--session-id S] [--json]"
)
EPHEMERAL_ENV_GET_USAGE = (
    "yoke ephemeral-env get PROJECT BRANCH [--session-id S] [--json]"
)


def ephemeral_env_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ephemeral-env get",
        usage=EPHEMERAL_ENV_GET_USAGE,
    )
    parser.add_argument("project", help="Project that owns the environment.")
    parser.add_argument("branch", help="Git branch the environment serves.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPHEMERAL_ENV_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        from yoke_cli.transport.human_values import write_human

        write_human((response.result or {}).get("environment", {}), stdout)

    return dispatch_and_emit(
        function_id="ephemeral_env.get",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload={"project": parsed.project, "branch": parsed.branch},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def ephemeral_env_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ephemeral-env create",
        usage=EPHEMERAL_ENV_CREATE_USAGE,
    )
    parser.add_argument("project", help="Project that owns the environment.")
    parser.add_argument("branch", help="Git branch the environment serves.")
    parser.add_argument(
        "--item",
        default="",
        help="Work item the environment is for, as PREFIX-N.",
    )
    parser.add_argument(
        "--workflow-run-id",
        default="",
        help="Workflow run that created the environment.",
    )
    parser.add_argument(
        "--github-ref",
        default="",
        help="Git ref the environment was built from.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPHEMERAL_ENV_CREATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="ephemeral_env.create",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload={
            "project": parsed.project,
            "branch": parsed.branch,
            "item": parsed.item,
            "workflow_run_id": parsed.workflow_run_id,
            "github_ref": parsed.github_ref,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def ephemeral_env_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ephemeral-env update",
        usage=EPHEMERAL_ENV_UPDATE_USAGE,
    )
    parser.add_argument("env_id", help="Ephemeral environment id.")
    parser.add_argument("field", help="Field to change.")
    parser.add_argument("value", help="New value for the field.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPHEMERAL_ENV_UPDATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result, stdout)

    return dispatch_and_emit(
        function_id="ephemeral_env.update",
        target=TargetRef(kind="global"),
        payload={
            "env_id": parsed.env_id,
            "field": parsed.field,
            "value": parsed.value,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "EPHEMERAL_ENV_CREATE_USAGE",
    "EPHEMERAL_ENV_GET_USAGE",
    "EPHEMERAL_ENV_UPDATE_USAGE",
    "ephemeral_env_create",
    "ephemeral_env_get",
    "ephemeral_env_update",
]
