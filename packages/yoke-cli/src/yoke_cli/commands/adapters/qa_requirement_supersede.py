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
    "[--declare-replacement | --reconcile] [--source operator|agent] [--session-id S] [--json]"
)

_EPILOG = (
    "Discharge a failed case whose defect only became visible after it was "
    "materialized, using a corrected case that actually passed instead of a "
    "waiver. The usual route records this for you: materialize the corrected "
    "case with --replaces CASE_KEY=FAILED_REQUIREMENT_ID on 'yoke qa plan run' "
    "or 'yoke qa plan materialize', and its passing independent verdict "
    "supersedes the failed case automatically. By hand, the corrected case "
    "must be bound to the same run, stage, member and deployment target (for "
    "an item case: the same item, transition, phase and target), be blocking, "
    "and have a recorded "
    "passing verdict. The superseded row is left exactly as it is, so what "
    "went wrong stays readable; the stage gate reads its obligation as "
    "answered by the named case. Order matters: record the replacement's "
    "passing verdict FIRST -- run its case, or submit the review bundle that "
    "settles it -- and supersede after. A replacement with no recorded pass "
    "yet is refused. For a failed case -- an admitted run case, or an item "
    "case of the same item, transition and phase -- with a corrected "
    "requirement already created, --declare-replacement atomically links "
    "that pending blocking case, skips the failed capture in the scoped "
    "roster, and wakes a run case's holder. A pass then supersedes "
    "automatically. "
    "A case that has not yet recorded a "
    "determinate verdict is still correctable in place with "
    "'yoke qa requirement update' -- supersession is for one that has already "
    "answered. Superseding an admitted copy is run-local: its item source "
    "row is untouched and still outstanding, so the next release admits the "
    "same body again. The receipt names that row and how to retire it. To "
    "retire a post_deploy item source, record the corrected body as a new "
    "item requirement for the same item, transition, phase and resolved environment "
    "(--target-env names the source snapshot destination; its digest need not match) "
    "('yoke qa requirement add --item ...'), then supersede the source with "
    "it. Neither item row ever executes, so this needs one admitted copy of "
    "the source replaced or superseded along a chain whose terminal case has a "
    "current configuration-and-target-qualified pass; that case answers "
    "its own run, and later releases admit only the corrected requirement. "
    "Successor links must converge on the named terminal case; supersession "
    "updates an existing replacement link to that same case. To repair "
    "inconsistent links, an operator or project steering holder runs this "
    "command with --reconcile --source operator and the unique terminal "
    "requirement. Divergent terminals, cycles, missing rows or incompatible "
    "scopes refuse before writing. The repair preserves intermediate rows, "
    "captures and prior rationale, and appends the verified actor, seat claim, "
    "scope and reason. Operator-sourced reconciliation requires a live operator "
    "session or steering seat covering the requirement, without the item claim. "
    "The item claim alone is insufficient. The holder is notified and retains "
    "its claim; the receipt reports notice delivery and any recovery."
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
        # Printed here rather than left in the envelope: this is the only
        # moment the operator holds the corrected configuration, and the
        # source row is the only thing that makes the correction stick.
        repair_notice = result.get("repair_notice")
        if repair_notice:
            print(f"Holder notice: {repair_notice['delivery']}", file=stdout)
            if repair_notice.get("recovery"):
                print(repair_notice["recovery"], file=_stderr)
        notice = result.get("next_admission_notice")
        if notice:
            print(f"Next release: {notice}", file=stdout)
        run_answer = result.get("run_replacement_requirement_id")
        if run_answer:
            print(
                f"Source retired: passing run case {run_answer} answers its run; "
                "later releases admit the corrected item requirement.",
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
        help="The frozen qa_requirements.id being discharged, or the post_deploy item source being retired.",
    )
    parser.add_argument(
        "--superseded-by-requirement-id",
        dest="superseded_by_requirement_id",
        type=int,
        required=True,
        help="The corrected qa_requirements.id that passed in its place, or the corrected item requirement retiring a source.",
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
    parser.add_argument(
        "--declare-replacement",
        action="store_true",
        help="Link a pending corrected direct case before its pass; the scoped plan runner executes it.",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Operator-authorized repair of links converging on the named terminal; preserves correction history.",
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
            "superseded_by_requirement_id": int(parsed.superseded_by_requirement_id),
            "rationale": rationale,
            "source": parsed.source,
            "declare_replacement": parsed.declare_replacement,
            "reconcile": parsed.reconcile,
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
