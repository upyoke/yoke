"""CLI adapter for durable QA requirement ownership transfers."""

import argparse
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

QA_REQUIREMENT_TRANSFER_USAGE = (
    "yoke qa requirement transfer --requirement-id N --to-item PREFIX-N "
    "--workflow-transition STAGE --rationale TEXT [--json]"
)


def qa_requirement_transfer(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement transfer",
        description=QA_REQUIREMENT_TRANSFER_USAGE,
        epilog="Hold both item work claims in one project. Only an unexecuted direct case can move; frozen plan/run cases and settled history retain their subject. A blocking case must retain its registered method. The receipt is recorded on both items; this command records no pass.",
    )
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--to-item", required=True)
    parser.add_argument("--workflow-transition", required=True)
    parser.add_argument("--rationale", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_TRANSFER_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.requirement.transfer",
        target=TargetRef(
            kind="qa_requirement", qa_requirement_id=parsed.requirement_id
        ),
        payload={
            "destination": parsed.to_item,
            "workflow_transition_id": parsed.workflow_transition,
            "rationale": parsed.rationale,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
