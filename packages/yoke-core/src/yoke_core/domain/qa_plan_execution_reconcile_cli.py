"""Settle a QA plan execution whose owner can no longer settle it."""

import argparse
import json
import sys

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import build_actor
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, _call_plan_function
from yoke_core.domain.qa_plan_execution_abort_reason import ABORT_REASON_MAX_LENGTH

EPILOG = (
    "Requires a live steering seat covering the project; other sessions are "
    "refused with steering_seat_required (yoke claims steering acquire --project "
    "P --reason TEXT). Refuses qa_reconcile_execution_live while the owner still "
    "heartbeats. A held host lease without recorded recovery refuses "
    "qa_reconcile_host_recovery_required, records cancellation and names the "
    "exact yoke test-machine reset or operator-release command; run it, then "
    "retry. A pending review passes to the caller (outcome review_handoff, or "
    "aborted when cancellation was recorded) and next_command names its "
    "review-begin; otherwise the execution settles as aborted with no verdict. "
    "The receipt row lives in qa_plan_execution_reconciliations."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan reconcile", description=__doc__, epilog=EPILOG
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument(
        "--reason",
        required=True,
        help=f"Why the owner cannot settle it, at most {ABORT_REASON_MAX_LENGTH} characters.",
    )
    parser.add_argument("--session-id")
    parser.add_argument("--json", action="store_true")
    parsed = parser.parse_args(argv)
    if len(parsed.reason) > ABORT_REASON_MAX_LENGTH:
        parser.error(
            f"reconcile_reason_too_long: --reason is {len(parsed.reason)} "
            f"characters; the limit is {ABORT_REASON_MAX_LENGTH}. Nothing changed. "
            "Move the full rationale to the Progress Log and retry."
        )
    try:
        result = _call_plan_function(
            function_id="qa.plan_execution.reconcile",
            target=TargetRef(kind="global", project_id=parsed.project),
            payload={"execution_id": parsed.execution_id, "reason": parsed.reason},
            actor=build_actor(session_id=parsed.session_id),
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan reconcile: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
