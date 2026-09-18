"""``yoke qa requirement supersede`` flag adapter."""

from __future__ import annotations

import argparse
import json
from typing import List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import (
    add_stdin_flag,
    add_text_file_pair,
    resolve_one_text_source,
)
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef


QA_REQUIREMENT_SUPERSEDE_USAGE = (
    "yoke qa requirement supersede --requirement-id N "
    "--superseded-by-requirement-id N "
    "(--rationale TEXT | --content-file PATH | --stdin) "
    "[--source operator|agent] [--session-id S] [--json]"
)

_EPILOG = (
    "Discharge a frozen deployment-run case whose defect only became visible "
    "after it was materialized, using a corrected case that actually passed "
    "instead of a waiver. The corrected case must be bound to the same run, "
    "stage, member and deployment target, be blocking, and have a recorded "
    "passing verdict. The superseded row is left exactly as it is, so what "
    "went wrong stays readable; the stage gate reads its obligation as "
    "answered by the named case. A run-bound case that has not yet recorded a "
    "determinate verdict is still correctable in place with "
    "'yoke qa requirement update' -- supersession is for one that has already "
    "answered."
)


def _write_supersede_result(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    result = response.result
    if "requirement_id" in result and "superseded_by_requirement_id" in result:
        print(
            f"Requirement {result['requirement_id']} superseded by "
            f"{result['superseded_by_requirement_id']} "
            f"(source={result['supersession_source']})",
            file=stdout,
        )
    else:
        print(json.dumps(result, sort_keys=True), file=stdout)


def qa_requirement_supersede(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement supersede",
        description=QA_REQUIREMENT_SUPERSEDE_USAGE,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="The frozen qa_requirements.id being discharged.",
    )
    parser.add_argument(
        "--superseded-by-requirement-id",
        dest="superseded_by_requirement_id",
        type=int,
        required=True,
        help="The corrected qa_requirements.id that passed in its place.",
    )
    rationale_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        rationale_group,
        "--rationale",
        "--content-file",
        dest="rationale",
        help_text="Why the corrected case answers the frozen one's obligation.",
        file_help="Read the supersession rationale from a path.",
    )
    add_stdin_flag(
        rationale_group, help_text="Read the supersession rationale from stdin."
    )
    parser.add_argument(
        "--source",
        choices=("operator", "agent"),
        default="agent",
        help="Supersession authority source.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_SUPERSEDE_USAGE)
    if parsed is None:
        return 2
    try:
        rationale = resolve_one_text_source(
            positional=parsed.rationale,
            file_path=parsed.rationale_file,
            stdin=parsed.stdin,
            positional_label="--rationale",
            file_flag="--content-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="qa.requirement.supersede",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload={
            "superseded_by_requirement_id": int(
                parsed.superseded_by_requirement_id
            ),
            "rationale": rationale,
            "source": parsed.source,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_supersede_result,
    )


USAGE_BY_FUNCTION_ID = {
    "qa.requirement.supersede": QA_REQUIREMENT_SUPERSEDE_USAGE,
}


__all__ = [
    "QA_REQUIREMENT_SUPERSEDE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_requirement_supersede",
]
