"""Deployment-run membership and composition CLI adapters."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


ADD_ITEM_USAGE = (
    "yoke deployment-runs add-item RUN-ID PREFIX-N "
    "[--project P] [--session-id S] [--json]"
)
VALIDATE_COMPOSITION_USAGE = (
    "yoke deployment-runs validate-composition RUN-ID "
    "[--session-id S] [--json]"
)


def deployment_runs_add_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs add-item",
        description=(
            "Attach one public item reference to a created deployment run. "
            "Requires the caller's project deploy lock."
        ),
    )
    parser.add_argument("run_id")
    parser.add_argument("item")
    parser.add_argument("--project")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ADD_ITEM_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.add_item",
        target=item_target("item", parsed.item, parsed.project),
        payload={"run_id": parsed.run_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def deployment_runs_validate_composition(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs validate-composition",
        description=(
            "Validate the current deployment-run membership before "
            "execution. Requires the caller's project deploy lock."
        ),
    )
    parser.add_argument("run_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VALIDATE_COMPOSITION_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        print((response.result or {}).get("message", ""), file=stdout)

    return dispatch_and_emit(
        function_id="deployment_runs.validate_composition",
        target=TargetRef(
            kind="workflow_run",
            workflow_run_id=parsed.run_id,
        ),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "ADD_ITEM_USAGE",
    "VALIDATE_COMPOSITION_USAGE",
    "deployment_runs_add_item",
    "deployment_runs_validate_composition",
]
