"""Operator adapter for the exact-stage deployment approval verdict."""

from __future__ import annotations

import argparse
from typing import List

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    emit_response,
    parse_or_usage_error,
)


FUNCTION_ID = "deployment_runs.stage_approval.evaluate"


DEPLOYMENT_RUNS_STAGE_APPROVAL_EVALUATE_USAGE = (
    "yoke deployment-runs stage-approval evaluate RUN-ID --stage STAGE "
    "[--session-id S] [--json]"
)
USAGE = DEPLOYMENT_RUNS_STAGE_APPROVAL_EVALUATE_USAGE

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

    # The whole point of this operation is that the serving build derives
    # the verdict. Dispatching on the caller's own connection would evaluate
    # with the caller's revision — which is exactly the defect this replaces,
    # and an admin connection is the shape most likely to hit it.
    from yoke_core.domain.control_plane_transport import (
        ServingControlPlaneUnresolved,
        serving_control_plane_env,
    )

    try:
        relay_env = serving_control_plane_env() or None
    except ServingControlPlaneUnresolved as exc:
        return emit_response(
            FunctionCallResponse(
                success=False,
                function=FUNCTION_ID,
                version="v1",
                error=FunctionError(
                    code="serving_control_plane_unresolved",
                    message=str(exc),
                ),
            ),
            json_mode=parsed.json_mode,
        )

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
        function_id=FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=parsed.run_id),
        payload={"stage": parsed.stage},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        relay_env=relay_env,
    )


__all__ = [
    "DEPLOYMENT_RUNS_STAGE_APPROVAL_EVALUATE_USAGE",
    "deployment_runs_stage_approval_evaluate",
]
