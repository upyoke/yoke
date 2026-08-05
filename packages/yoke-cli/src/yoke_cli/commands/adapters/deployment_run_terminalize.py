"""CLI adapter for audited deployment-run terminalization."""

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


DEPLOYMENT_RUNS_TERMINALIZE_USAGE = (
    "yoke deployment-runs terminalize RUN-ID "
    "--disposition {failed,cancelled} --reason TEXT "
    "[--session-id S] [--json]"
)


def deployment_runs_terminalize(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs terminalize",
        description=(
            "Close an active deployment run with a permanent audit event."
        ),
    )
    parser.add_argument("run_id")
    parser.add_argument(
        "--disposition", required=True, choices=("failed", "cancelled"),
    )
    parser.add_argument(
        "--reason", required=True,
        help="Operator rationale retained in the permanent audit event.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, DEPLOYMENT_RUNS_TERMINALIZE_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        print(
            f"Terminalized {result.get('run_id', parsed.run_id)}: "
            f"{result.get('prior_status', '')} -> "
            f"{result.get('final_status', parsed.disposition)}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="deployment_runs.terminalize",
        target=TargetRef(
            kind="workflow_run", workflow_run_id=parsed.run_id,
        ),
        payload={
            "disposition": parsed.disposition,
            "reason": parsed.reason,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "DEPLOYMENT_RUNS_TERMINALIZE_USAGE",
    "deployment_runs_terminalize",
]
