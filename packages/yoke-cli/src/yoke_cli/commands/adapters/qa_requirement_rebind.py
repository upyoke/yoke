"""``yoke qa requirement rebind-target`` flag adapter."""

from __future__ import annotations

import argparse
from yoke_cli.transport.human_values import write_human
from typing import List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import add_stdin_flag, resolve_one_text_source
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef


QA_REQUIREMENT_REBIND_TARGET_USAGE = (
    "yoke qa requirement rebind-target --requirement-id N "
    "(--rationale TEXT | --content-file PATH | --stdin) "
    "[--session-id S] [--json]"
)

_EPILOG = """\
Point a QA case at the current declaration of the environment it already
tested, keeping its recorded runs and verdict. Use it when the environment
is the same but its stored fingerprint (digest) is stale: a settings write
changed the digest without changing which host it resolves to, or the
snapshot's endpoints already match while its site or other labels are out
of date. A change of URL scheme alone (in hosts.*) is the same environment;
a host that now resolves to a different host and port is a different
target, and the command refuses. The result shows what changed in the
endpoints and keeps the previous target (execution_target_json) for later
readers. This is not a waiver and not a new verification. A live item's QA
case cannot be superseded, so this is how to update it.

The environment used is the snapshot's environment id; else the case's own
target_env on the snapshot's (or the plan target's) site; else the plan's
default target; else the snapshot's site and environment names.

Run it from the session holding the item's work claim, a live steering seat
covering the item, or the live driver of the case's deployment run.
"""


def _write_rebind_result(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    result = response.result
    if "requirement_id" not in result:
        write_human(result, stdout)
        return
    status = "already current" if result.get("already_current") else "rebound"
    print(
        f"Requirement {result['requirement_id']} {status} "
        f"{result.get('from_digest', '')} -> {result.get('to_digest', '')}",
        file=stdout,
    )
    delta = result.get("endpoint_delta") or {}
    changed = delta.get("changed") or []
    if changed:
        parts = [
            f"{row.get('key')} {row.get('from')!r} -> {row.get('to')!r} "
            f"({row.get('kind')})"
            for row in changed
            if isinstance(row, dict)
        ]
        print("endpoint delta: " + "; ".join(parts), file=stdout)


def qa_requirement_rebind_target(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement rebind-target",
        usage=QA_REQUIREMENT_REBIND_TARGET_USAGE,
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id whose stored target digest is stale.",
    )
    rationale_group = parser.add_mutually_exclusive_group(required=True)
    rationale_group.add_argument(
        "--rationale",
        dest="rationale",
        metavar="TEXT",
        help="Why the stored evidence still applies to this environment.",
    )
    rationale_group.add_argument(
        "--content-file",
        dest="rationale_file",
        metavar="PATH",
        help="Read the rationale from this file.",
    )
    add_stdin_flag(rationale_group, help_text="Read the rationale from stdin.")
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
