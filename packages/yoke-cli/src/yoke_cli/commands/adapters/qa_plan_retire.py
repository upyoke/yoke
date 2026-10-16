"""``yoke qa plan retire`` adapter."""

from __future__ import annotations

import argparse
from typing import List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import (
    add_stdin_flag,
    add_text_file_pair,
    resolve_one_text_source,
)


QA_PLAN_RETIRE_USAGE = (
    "yoke qa plan retire PLAN [--project P] "
    "(--reason TEXT | --content-file PATH | --stdin) [--session-id S] [--json]"
)

QA_PLAN_RETIRE_EPILOG = """\
Retire a project QA plan that nothing depends on any more.

Worked example:

  yoke qa plan retire hosted-installer-continue-correction --project yoke \\
    --reason "only case is unrunnable; its one requirement was retracted"

PLAN is the plan slug or its numeric id. Run it from a session holding a
live steering seat covering the plan's project; other callers refuse with
steering_seat_required and the seat recipe.

Retirement records retired_at with the reason and the acting actor. The
plan stays readable: `yoke qa plan get PLAN` shows it, and
`yoke qa plan list --include-retired` lists it with its retirement. It
refuses edits and materialization from then on. Requirements and runs
already recorded keep their evidence.

The command refuses with qa_plan_retire_dependents while anything still
needs the plan, naming each one with the command that settles it:
  - an unsettled requirement whose newest attempt has not passed
    (unexecuted item copies: `yoke qa item-plan retract`; otherwise
    `yoke qa requirement waive` or `supersede`)
  - an in-flight execution whose roster reaches the plan
    (let it finish, or `yoke qa plan abort`)
  - a project default that would attach the plan to new items
    (`yoke qa project-default unset`)

Copies on a finished item never hold the plan: nothing can run them again,
and a finished item cannot be claimed to retract them. Retirement retracts
their unexecuted copies (and the attachment) in the same transaction and
returns their ids in retracted_requirement_ids; executed copies stay as
history.

Repeating the command on a retired plan returns the recorded retirement
unchanged (already_retired true), so a retry after a lost reply is safe.
There is no un-retire: author a new plan with `yoke qa plan create`.

Exit codes: 0 retired or already retired; 1 refused or dispatch failure;
2 command-line usage error.
"""


def qa_plan_retire(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan retire",
        description=QA_PLAN_RETIRE_USAGE,
        epilog=QA_PLAN_RETIRE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("plan", help="Plan slug or numeric id.")
    add_project_arg(parser)
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(
        reason_group,
        "--reason",
        "--content-file",
        dest="reason",
        help_text="Why the plan is retired; stored as its retirement record.",
        file_help="Read the reason from a path.",
    )
    add_stdin_flag(reason_group, help_text="Read the reason from stdin.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_PLAN_RETIRE_USAGE)
    if parsed is None:
        return 2
    project = client_project_context(parsed.project)
    if project is None:
        return usage_error(
            "project context required: pass --project P, set YOKE_PROJECT, "
            "or run from a checkout mapped in machine config"
        )
    try:
        reason = resolve_one_text_source(
            positional=parsed.reason,
            file_path=parsed.reason_file,
            stdin=parsed.stdin,
            positional_label="--reason",
            file_flag="--content-file",
        )
    except ValueError as exc:
        return usage_error(str(exc))
    return dispatch_and_emit(
        function_id="qa.plan.retire",
        target=TargetRef(kind="global"),
        payload={"project": project, "plan": parsed.plan, "reason": reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


USAGE_BY_FUNCTION_ID = {
    "qa.plan.retire": QA_PLAN_RETIRE_USAGE,
}


__all__ = [
    "QA_PLAN_RETIRE_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_plan_retire",
]
