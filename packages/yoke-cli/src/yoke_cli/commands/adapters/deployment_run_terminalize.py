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
from yoke_cli.commands.adapters.github_actions_run_cancel import (
    print_workflow_cancellation,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.deployment_itemless_teaching import (
    INTERRUPTED_RUN_RECOVERY,
)


DEPLOYMENT_RUNS_TERMINALIZE_USAGE = (
    "yoke deployment-runs terminalize RUN-ID "
    "--disposition {failed,cancelled} --reason TEXT "
    "[--session-id S] [--json]"
)


def deployment_runs_terminalize(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs terminalize",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Close an active deployment run with a permanent failed or "
            "cancelled audit event, then cancel every GitHub workflow the "
            "run dispatched. An interrupted driver whose GitHub "
            "workflow is still running or already succeeded is recovered "
            "by re-driving the same run, not by terminalize."
        ),
        epilog=INTERRUPTED_RUN_RECOVERY,
    )
    parser.add_argument("run_id", help="Id of the active deployment run to close.")
    parser.add_argument(
        "--disposition",
        required=True,
        choices=("failed", "cancelled"),
        help="Final state to record: failed or cancelled.",
    )
    parser.add_argument(
        "--reason",
        required=True,
        help="Operator rationale retained in the permanent audit event.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        DEPLOYMENT_RUNS_TERMINALIZE_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"Terminalized {result.get('run_id', parsed.run_id)}: "
            f"{result.get('prior_status', '')} -> "
            f"{result.get('final_status', parsed.disposition)}",
            file=stdout,
        )
        # A serving build older than workflow cancellation omits the list.
        for entry in result.get("workflow_cancellations") or []:
            print_workflow_cancellation(entry, stdout=stdout, stderr=stderr)

    return dispatch_and_emit(
        function_id="deployment_runs.terminalize",
        target=TargetRef(
            kind="workflow_run",
            workflow_run_id=parsed.run_id,
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
