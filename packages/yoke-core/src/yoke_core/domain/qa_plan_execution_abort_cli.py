"""Explicit operator cleanup for an interrupted ordered QA plan execution."""

from __future__ import annotations

import argparse
from yoke_core.domain.json_helper import dumps_compact
import sys
from typing import List, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError, _call_plan_function
from yoke_core.domain.qa_plan_execution_abort_reason import ABORT_REASON_MAX_LENGTH

REASON_HELP = (
    f"Why the execution stops, at most {ABORT_REASON_MAX_LENGTH} characters: "
    "a code, then a short diagnosis (blocked_on_precondition: <prerequisite "
    "and recovery>). Put the full rationale in the Progress Log or an "
    "artifact and cite it here."
)


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan abort",
        description=(
            "Stop an ordered QA execution. In-flight host work retains custody "
            "until restore proof is recorded. The owner stops its own execution. "
            "A live steering seat stops another session's live execution: the "
            "receipt reads outcome stop_requested, and the owner's runner stops "
            "at its next case or heartbeat, cleans up its host and settles it. "
            "Any session may abandon an execution whose owner has not "
            "heartbeated for 30 minutes and is not parked."
        ),
        epilog=(
            "qa_abort_restore_pending means cancellation is recorded: keep the "
            "runner connected through cleanup, then retry. Failed restoration "
            "retains the lease and names operator recovery. "
            "qa_execution_stop_requires_steering means another session still "
            "drives the walk: acquire a steering seat with yoke claims steering "
            "acquire --project P --reason TEXT and rerun, or ask the owner. "
            "See yoke qa plan run --help."
        ),
    )
    parser.add_argument("--item", help="Item whose QA execution to abort, as PREFIX-N.")
    parser.add_argument("--execution-id", required=True, help="QA execution to abort.")
    parser.add_argument("--reason", required=True, help=REASON_HELP)
    parser.add_argument("--project", help="Project that owns the execution.")
    parser.add_argument(
        "--session-id",
        help="Override the detected session id (debugging only).",
    )
    parsed = parser.parse_args(args)
    if len(parsed.reason) > ABORT_REASON_MAX_LENGTH:
        parser.error(
            f"abort_reason_too_long: --reason is {len(parsed.reason)} characters; "
            f"the limit is {ABORT_REASON_MAX_LENGTH}. Nothing was aborted. Keep "
            "the code and a short diagnosis, move the full rationale to the "
            "Progress Log or an artifact, and retry."
        )

    from yoke_core.api.service_client_structured_api_adapter import build_actor

    target = (
        TargetRef(
            kind="item",
            public_ref=str(parsed.item),
            project_id=parsed.project,
        )
        if parsed.item
        else TargetRef(kind="global", project_id=parsed.project)
    )
    try:
        result = _call_plan_function(
            function_id="qa.plan_execution.abort",
            target=target,
            payload={
                "execution_id": parsed.execution_id,
                "reason": parsed.reason,
            },
            actor=build_actor(session_id=parsed.session_id),
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan abort: {exc}", file=sys.stderr)
        return 2
    receipt = {
        key: result.get(key)
        for key in (
            "execution_id",
            "item_id",
            "deployment_run_id",
            "transition_id",
            "state",
            "cursor_ordinal",
            "test_machine_lease_id",
        )
    }
    if result.get("standalone_plan_id") is not None:
        receipt["standalone_plan_id"] = result["standalone_plan_id"]
    if result.get("stop_request") is not None:
        receipt["stop_request"] = result["stop_request"]
    print(dumps_compact(receipt))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
