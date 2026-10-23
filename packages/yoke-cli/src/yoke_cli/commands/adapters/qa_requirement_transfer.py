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
    "--workflow-transition STAGE --rationale TEXT [--session-id S] [--json]"
)


def qa_requirement_transfer(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement transfer",
        usage=QA_REQUIREMENT_TRANSFER_USAGE,
        epilog=(
            "You must hold the work claims of both items, and both must be in\n"
            "one project. Only a requirement that has not run and was added\n"
            "directly can move; requirements from a frozen plan or run, and\n"
            "settled history, stay with their item. A blocking requirement must\n"
            "keep a way to run it, or the new item must accept manual review\n"
            "for it. Both items record the move; this command records no pass."
        ),
    )
    parser.add_argument(
        "--requirement-id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id to move.",
    )
    parser.add_argument(
        "--to-item", required=True, metavar="PREFIX-N", help="Item to move it to."
    )
    parser.add_argument(
        "--workflow-transition",
        required=True,
        metavar="STAGE",
        help="Workflow transition it gates on the new item.",
    )
    parser.add_argument(
        "--rationale", required=True, metavar="TEXT", help="Why the requirement moves."
    )
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
