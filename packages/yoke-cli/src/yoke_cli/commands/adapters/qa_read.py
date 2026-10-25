"""Public-item QA catalog and read adapters."""

from __future__ import annotations

import argparse
from yoke_cli.commands.adapters.list_paging import add_page_args, dispatch_list

from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef

QA_REQUIREMENT_LIST_USAGE = (
    "yoke qa requirement list [--item PREFIX-N | --epic PREFIX-N | "
    "--deployment-run-id ID] [--project P] [--limit N] [--offset N] [--full] [--session-id S] [--json]"
)

_REQUIREMENT_LIST_HELP_DEEP = """\
List QA requirements. Pass one filter, or none to list every requirement in
the project. When several are passed, --item wins, then --deployment-run-id,
then --epic.

  yoke qa requirement list --item YOK-N
  yoke qa requirement list --epic YOK-1704 --json

The --epic filter returns the requirements of every task in the epic; filter
by task_num yourself. Exit codes: 0 success, 1 dispatch failure, 2 usage.
"""


def qa_requirement_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement list",
        usage=QA_REQUIREMENT_LIST_USAGE,
        description=_REQUIREMENT_LIST_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Only this item's requirements.",
    )
    parser.add_argument(
        "--epic",
        dest="epic",
        default=None,
        metavar="PREFIX-N",
        help="Only the requirements of this epic's tasks.",
    )
    parser.add_argument(
        "--deployment-run-id",
        dest="deployment_run_id",
        default=None,
        metavar="ID",
        help="Only this deployment run's requirements (run-YYYYMMDD-NNN).",
    )
    add_page_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.item is not None:
        target = item_target("item", parsed.item, parsed.project)
    elif parsed.deployment_run_id is not None:
        target = TargetRef(
            kind="deployment_run",
            deployment_run_id=parsed.deployment_run_id,
        )
    else:
        target = TargetRef(
            kind="global", project_id=client_project_context(parsed.project)
        )
        if parsed.epic is not None:
            payload["epic_public_ref"] = parsed.epic
    return dispatch_list(
        parsed=parsed,
        function_id="qa.requirement.list",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_REQUIREMENT_GET_USAGE = "yoke qa requirement get (N | --requirement-id N) [--full] [--session-id S] [--json]"

_REQUIREMENT_GET_HELP_DEEP = """\
Show one QA requirement by its id. Pass the id positionally or with
--requirement-id, not both.

  yoke qa requirement get 5731

Exit codes: 0 success, 1 not found / dispatch failure, 2 usage error.
"""


def qa_requirement_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement get",
        usage=QA_REQUIREMENT_GET_USAGE,
        description=_REQUIREMENT_GET_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "requirement", nargs="?", type=int, metavar="N", help="QA requirement id."
    )
    parser.add_argument(
        "--requirement-id", type=int, metavar="N", help="QA requirement id."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_GET_USAGE)
    if parsed is None:
        return 2
    if (parsed.requirement is None) == (parsed.requirement_id is None):
        return usage_error(
            "provide exactly one requirement id, positionally or with --requirement-id"
        )
    requirement_id = (
        parsed.requirement if parsed.requirement is not None else parsed.requirement_id
    )
    return dispatch_and_emit(
        function_id="qa.requirement.get",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(requirement_id),
        ),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_RUN_LIST_USAGE = (
    "yoke qa run list [--requirement-id N] [--project P] [--limit N] [--offset N] [--full] [--session-id S] "
    "[--json]"
)

_RUN_LIST_HELP_DEEP = """\
With --requirement-id, list that requirement's runs: the current run first
(latest start time, then highest id), then the older runs, newest id first.
A run with a missing or invalid start time refuses the list with
qa_execution_order_ambiguous. Without --requirement-id, list every run in the
project, oldest id first (for debugging; agents filter by requirement).

  yoke qa run list --requirement-id 5731

Each row keeps the captured execution_status, raw_result and verdict;
case_outcome is the judged outcome, including final capture reviews.
Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def qa_run_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run list",
        usage=QA_RUN_LIST_USAGE,
        description=_RUN_LIST_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        default=None,
        metavar="N",
        help="Only runs of this QA requirement id.",
    )
    add_project_arg(parser)
    add_page_args(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_LIST_USAGE)
    if parsed is None:
        return 2
    if parsed.requirement_id is not None:
        target = TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        )
    else:
        target = TargetRef(
            kind="global", project_id=client_project_context(parsed.project)
        )
    return dispatch_list(
        parsed=parsed,
        function_id="qa.run.list",
        target=target,
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_RUN_GET_USAGE = (
    "yoke qa run get --run-id N [--project P] [--full] [--session-id S] [--json]"
)
_RUN_GET_HELP_DEEP = """\
Show one QA run with its judged case_outcome and captured evidence. The
project comes from --project, then $YOKE_PROJECT, then the checkout's mapped
project; a run from another project is refused.

  yoke qa run get --run-id 8142
"""


def qa_run_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run get",
        usage=QA_RUN_GET_USAGE,
        description=_RUN_GET_HELP_DEEP,
    )
    parser.add_argument(
        "--run-id",
        dest="run_id",
        type=int,
        required=True,
        metavar="N",
        help="The QA run's id.",
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_GET_USAGE)
    if parsed is None:
        return 2
    project = client_project_context(parsed.project)
    if not project:
        return usage_error(
            "project context required: pass --project P, set YOKE_PROJECT, "
            "or run from a registered project checkout"
        )
    return dispatch_and_emit(
        function_id="qa.run.get",
        target=TargetRef(kind="global", project_id=str(project)),
        payload={"run_id": int(parsed.run_id), "project": str(project)},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_GATE_SUMMARY_USAGE = (
    "yoke qa gate-summary (--item PREFIX-N | --epic PREFIX-N --task-num K) "
    "--target {reviewed-implementation,implemented} [--project P] [--full] "
    "[--session-id S] [--json]"
)

_GATE_SUMMARY_HELP_DEEP = """\
List which blocking QA requirements still lack the evidence their kind
requires before a work item or epic task can move to --target. It uses the
same rules as the gate itself and changes nothing. Pass --item, or both
--epic and --task-num.

  yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
  yoke qa gate-summary --epic YOK-1704 --task-num 5 --target implemented

reviewed-implementation checks only verification-phase requirements.
implemented checks blocking requirements from every phase; for an item it
also lists unsettled_records (latest runs without a verdict, live host
leases, active plan runs), and any entry makes the summary unsatisfied.
Exit codes: 0 success (satisfied or not), 1 dispatch failure, 2 usage error.
"""


def qa_gate_summary(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa gate-summary",
        usage=QA_GATE_SUMMARY_USAGE,
        description=_GATE_SUMMARY_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", default=None, metavar="PREFIX-N", help="The item.")
    parser.add_argument(
        "--epic",
        dest="epic",
        default=None,
        metavar="PREFIX-N",
        help="The epic (with --task-num).",
    )
    parser.add_argument(
        "--task-num",
        dest="task_num",
        type=int,
        default=None,
        metavar="K",
        help="The epic's task number, starting at 1 (with --epic).",
    )
    parser.add_argument(
        "--target",
        required=True,
        choices=("reviewed-implementation", "implemented"),
        help="The status the item or task is moving to.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_GATE_SUMMARY_USAGE)
    if parsed is None:
        return 2
    if parsed.item is not None:
        target = item_target("item", parsed.item, parsed.project)
    elif parsed.epic is not None and parsed.task_num is not None:
        target = TargetRef(
            kind="epic_task",
            public_ref=parsed.epic,
            task_num=int(parsed.task_num),
        )
    else:
        return usage_error(
            "gate-summary requires --item PREFIX-N OR both --epic and --task-num"
        )
    return dispatch_and_emit(
        function_id="qa.gate_summary.run",
        target=target,
        payload={"transition": parsed.target},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_REQUIREMENT_LIST_USAGE",
    "QA_REQUIREMENT_GET_USAGE",
    "QA_RUN_LIST_USAGE",
    "QA_RUN_GET_USAGE",
    "QA_GATE_SUMMARY_USAGE",
    "qa_requirement_list",
    "qa_requirement_get",
    "qa_run_list",
    "qa_run_get",
    "qa_gate_summary",
]
