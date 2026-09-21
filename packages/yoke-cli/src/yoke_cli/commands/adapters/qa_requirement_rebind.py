"""``yoke qa requirement rebind-target`` flag adapter."""

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


QA_REQUIREMENT_REBIND_TARGET_USAGE = (
    "yoke qa requirement rebind-target --requirement-id N "
    "(--rationale TEXT | --content-file PATH | --stdin) "
    "[--session-id S] [--json]"
)

_EPILOG = (
    "Point a requirement at the live declaration of the SAME environment "
    "identity, keeping its recorded runs and verdict. Use it when a settings "
    "write corrected declared facts (hosts, distribution, role) and moved the "
    "execution-target digest without changing which environment or subject "
    "the case ran against. It is not a waiver and not re-verification. A "
    "different environment, deployment, or subject still needs a fresh "
    "execution or sanctioned retirement/supersession; this command refuses "
    "those and says so."
)


def _write_rebind_result(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    result = response.result
    if "requirement_id" not in result:
        print(json.dumps(result, sort_keys=True), file=stdout)
        return
    status = "already current" if result.get("already_current") else "rebound"
    print(
        f"Requirement {result['requirement_id']} {status} "
        f"{result.get('from_digest', '')} -> {result.get('to_digest', '')}",
        file=stdout,
    )


def qa_requirement_rebind_target(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement rebind-target",
        description=QA_REQUIREMENT_REBIND_TARGET_USAGE,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="The qa_requirements.id whose stored target digest is stale.",
    )
    rationale_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        rationale_group,
        "--rationale",
        "--content-file",
        dest="rationale",
        help_text="Why the stored evidence still answers this environment.",
        file_help="Read the rebind rationale from a path.",
    )
    add_stdin_flag(rationale_group, help_text="Read the rebind rationale from stdin.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_REBIND_TARGET_USAGE)
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
        function_id="qa.requirement.rebind_target",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload={"rationale": rationale},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_rebind_result,
    )


USAGE_BY_FUNCTION_ID = {
    "qa.requirement.rebind_target": QA_REQUIREMENT_REBIND_TARGET_USAGE,
}


__all__ = [
    "QA_REQUIREMENT_REBIND_TARGET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_requirement_rebind_target",
]
