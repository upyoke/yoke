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
    "[--project P] [--intent progress|final] [--requirement-id N ...] "
    "[--plan-id N ...] [--session-id S] [--json]"
)
VALIDATE_COMPOSITION_USAGE = (
    "yoke deployment-runs validate-composition RUN-ID [--session-id S] [--json]"
)

# Deploying another project's code and carrying its items are separate facts,
# and the gap between them is invisible from the run: a reader sees only the
# members. Name it where the refusal lands.
CROSS_PROJECT_MEMBERSHIP_NOTE = """\
Membership is same-project only:
  An item whose project differs from the run's is refused. That holds even
  when the run deploys that project's code: a github-actions-workflow stage
  may declare `input_bindings`, resolving another registered project's branch
  tip at dispatch and shipping that commit alongside this run's own candidate.
  Check with `yoke deployment-flows stages FLOW-ID`.

  The bound project's items get no membership row, no requirement snapshot,
  and no deployment wake here — they stay at their release wait until a run on
  their own flow closes them out, which re-deploys a revision already serving.
  Plan that run as the delivery record, not as the thing that ships the code,
  and do not read its absence as proof the code is undeployed.
"""


def deployment_runs_add_item(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs add-item",
        description=(
            "Attach one public item reference to a created deployment run. "
            "Requires the caller's project deploy lock."
        ),
        epilog=CROSS_PROJECT_MEMBERSHIP_NOTE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_id")
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--intent", choices=("progress", "final"), default=None)
    parser.add_argument("--requirement-id", type=int, action="append", default=[])
    parser.add_argument("--plan-id", type=int, action="append", default=[])
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ADD_ITEM_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        print((response.result or {}).get("message", ""), file=stdout)

    payload = {"run_id": parsed.run_id}
    if parsed.intent is not None:
        payload["delivery_intent"] = parsed.intent
    if parsed.requirement_id:
        payload["requirement_ids"] = parsed.requirement_id
    if parsed.plan_id:
        payload["plan_ids"] = parsed.plan_id
    return dispatch_and_emit(
        function_id="deployment_runs.add_item",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
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
