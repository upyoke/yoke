"""Operator adapter for the exact-stage deployment approval verdict."""

from __future__ import annotations

import argparse
from typing import List

from yoke_contracts.api.function_call import TargetRef

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


USAGE = "yoke deployment-runs stage-approval evaluate RUN-ID --stage STAGE"

DESCRIPTION = """\
Report whether one EXACT deployment run stage's declared approval is
satisfied, and raise the decision request it calls for when none answers
for the stage yet.

Evaluating never approves. It reports what the stage is still waiting on;
a person records an answer through `yoke deployment-runs approve` or the
Inbox.

The verdict is derived by the build serving this control plane, so a
driver running a different revision than the deployed one gets an answer
computed against the schema that build actually converged. Read the stage
name from `yoke deployment-runs stages RUN-ID`; a run standing at another
stage is refused rather than evaluated.
"""


def deployment_runs_stage_approval_evaluate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke deployment-runs stage-approval evaluate",
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("run_id")
    parser.add_argument("--stage", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        state = "satisfied" if result.get("satisfied") else "waiting"
        stdout.write(
            f"{result.get('run_id')} stage {result.get('stage')!r}: {state} "
            f"(decision request {result.get('request_id')}, "
            f"{result.get('request_status')}) — {result.get('reason')}\n"
        )
        return None

    return dispatch_and_emit(
        function_id="deployment_runs.stage_approval.evaluate",
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={"stage": parsed.stage},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["deployment_runs_stage_approval_evaluate"]
