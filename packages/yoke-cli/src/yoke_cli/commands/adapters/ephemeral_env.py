"""``yoke ephemeral-env`` adapters."""

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


EPHEMERAL_ENV_UPDATE_USAGE = (
    "yoke ephemeral-env update ENV-ID FIELD VALUE [--session-id S] [--json]"
)
EPHEMERAL_ENV_CREATE_USAGE = (
    "yoke ephemeral-env create PROJECT BRANCH [--item PREFIX-N] "
    "[--workflow-run-id ID] [--github-ref REF] [--session-id S] [--json]"
)


def ephemeral_env_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ephemeral-env create",
        description=EPHEMERAL_ENV_CREATE_USAGE,
    )
    parser.add_argument("project")
    parser.add_argument("branch")
    parser.add_argument("--item", default="")
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--github-ref", default="")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPHEMERAL_ENV_CREATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        print((response.result or {}).get("env_id", ""), file=stdout)

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
        description=EPHEMERAL_ENV_UPDATE_USAGE,
    )
    parser.add_argument("env_id")
    parser.add_argument("field")
    parser.add_argument("value")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, EPHEMERAL_ENV_UPDATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(result.get("message", ""), file=stdout)
        return None

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
    "EPHEMERAL_ENV_UPDATE_USAGE",
    "ephemeral_env_create",
    "ephemeral_env_update",
]
