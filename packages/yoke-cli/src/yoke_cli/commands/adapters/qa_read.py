"""``yoke qa ...`` read-family flag adapters.

Four read function ids in one module — the typed replacements for the
db_router qa read fallbacks:

* ``qa.requirement.list`` — list ``qa_requirements`` rows filtered by
  item, epic, or deployment run.
* ``qa.requirement.get`` — one ``qa_requirements`` row by id.
* ``qa.run.list`` — list ``qa_runs`` rows, optionally per requirement.
* ``qa.run.get`` — one ``qa_runs`` row by id.
* ``qa.gate_summary.run`` — read-only unsatisfied-requirement summary
  for the advance/polish handoff (works over https; replaces the
  checkout-shaped ``db_router qa gate-summary`` agent recipe).
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


QA_REQUIREMENT_LIST_USAGE = (
    "yoke qa requirement list [--item PREFIX-N | --epic-id N | "
    "--deployment-run-id ID] [--session-id S] [--json]"
)

_REQUIREMENT_LIST_HELP_DEEP = """\
List qa_requirements rows. Exactly one filter (or none for every row);
precedence when several are passed: item, then epic, then deployment run.

Worked example:

  yoke qa requirement list --item YOK-N
  yoke qa requirement list --epic-id 1704 --json

Flag matrix:

  flag                 required  value shape
  --item               no        PREFIX-N or project-local number
  --epic-id            no        bare epic item id (integer)
  --deployment-run-id  no        run id string (run-YYYYMMDD-NNN)
  --session-id         no        opaque session id (operator-debug)
  --json               no        flag (typed envelope on stdout)

Epic filter returns every task's requirements for the epic; filter by
task_num client-side. Exit codes: 0 success, 1 dispatch failure, 2 usage.
"""


def qa_requirement_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement list",
        description=(
            f"{QA_REQUIREMENT_LIST_USAGE}\n\n{_REQUIREMENT_LIST_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", default=None,
                        help="Filter to one item (PREFIX-N or number).")
    parser.add_argument("--epic-id", dest="epic_id", type=int, default=None,
                        help="Filter to one epic's task requirements.")
    parser.add_argument("--deployment-run-id", dest="deployment_run_id",
                        default=None,
                        help="Filter to one deployment run.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.item is not None:
        target = item_target("item", parsed.item, parsed.project)
    else:
        target = TargetRef(kind="global")
        if parsed.epic_id is not None:
            payload["epic_id"] = int(parsed.epic_id)
        elif parsed.deployment_run_id is not None:
            payload["deployment_run_id"] = parsed.deployment_run_id
    return dispatch_and_emit(
        function_id="qa.requirement.list",
        target=target,
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_REQUIREMENT_GET_USAGE = (
    "yoke qa requirement get --requirement-id N [--session-id S] [--json]"
)

_REQUIREMENT_GET_HELP_DEEP = """\
Fetch one qa_requirements row by primary key.

Worked example:

  yoke qa requirement get --requirement-id 5731

Flag matrix:

  flag              required  value shape
  --requirement-id  yes       qa_requirements.id (integer)
  --session-id      no        opaque session id (operator-debug)
  --json            no        flag (typed envelope on stdout)

Exit codes: 0 success, 1 not found / dispatch failure, 2 usage error.
"""


def qa_requirement_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa requirement get",
        description=(
            f"{QA_REQUIREMENT_GET_USAGE}\n\n{_REQUIREMENT_GET_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="Target qa_requirements.id.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_REQUIREMENT_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.requirement.get",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_RUN_LIST_USAGE = (
    "yoke qa run list [--requirement-id N] [--session-id S] [--json]"
)

_RUN_LIST_HELP_DEEP = """\
List qa_runs rows, newest id last. Omit --requirement-id to list every
run (operator-debug breadth; agent calls filter by requirement).

Worked example:

  yoke qa run list --requirement-id 5731

Flag matrix:

  flag              required  value shape
  --requirement-id  no        owning qa_requirements.id (integer)
  --session-id      no        opaque session id (operator-debug)
  --json            no        flag (typed envelope on stdout)

Rows include execution_status (capture outcome) alongside verdict.
Exit codes: 0 success, 1 dispatch failure, 2 usage error.
"""


def qa_run_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run list",
        description=f"{QA_RUN_LIST_USAGE}\n\n{_RUN_LIST_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, default=None,
                        help="Owning qa_requirements.id.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_LIST_USAGE)
    if parsed is None:
        return 2
    if parsed.requirement_id is not None:
        target = TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        )
    else:
        target = TargetRef(kind="global")
    return dispatch_and_emit(
        function_id="qa.run.list",
        target=target,
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_RUN_GET_USAGE = (
    "yoke qa run get --run-id N [--session-id S] [--json]"
)

_RUN_GET_HELP_DEEP = """\
Fetch one qa_runs row by primary key.

Worked example:

  yoke qa run get --run-id 8142

Flag matrix:

  flag          required  value shape
  --run-id      yes       qa_runs.id (integer)
  --session-id  no        opaque session id (operator-debug)
  --json        no        flag (typed envelope on stdout)

Rows include execution_status (capture outcome) alongside verdict.
Exit codes: 0 success, 1 not found / dispatch failure, 2 usage error.
"""


def qa_run_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run get",
        description=f"{QA_RUN_GET_USAGE}\n\n{_RUN_GET_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--run-id", dest="run_id", type=int, required=True,
                        help="Target qa_runs.id.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.run.get",
        target=TargetRef(kind="global"),
        payload={"run_id": int(parsed.run_id)},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_GATE_SUMMARY_USAGE = (
    "yoke qa gate-summary (--item PREFIX-N | --epic-id N --task-num K) "
    "--target {reviewed-implementation,implemented} [--session-id S] [--json]"
)

_GATE_SUMMARY_HELP_DEEP = """\
Read-only summary of QA requirements for the advance/polish handoff —
which blocking requirements still lack the evidence their kind requires.
Shares satisfaction semantics with the verification gate
(yoke_core.domain.qa_gates); never mutates qa_runs/qa_requirements.

Worked example:

  yoke qa gate-summary --item YOK-N --target reviewed-implementation --json
  yoke qa gate-summary --epic-id 1704 --task-num 5 --target implemented

Flag matrix:

  flag          required          value shape
  --item        yes (or epic)     PREFIX-N or project-local number
  --epic-id     with --task-num   bare epic item id (integer)
  --task-num    with --epic-id    1-based task number (integer)
  --target      yes               reviewed-implementation | implemented
  --session-id  no                opaque session id (operator-debug)
  --json        no                flag (typed envelope on stdout)

reviewed-implementation scopes to qa_phase=verification; implemented
covers blocking requirements from every phase. Exit codes: 0 success
(regardless of satisfied state), 1 dispatch failure, 2 usage error.
"""


def qa_gate_summary(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa gate-summary",
        description=f"{QA_GATE_SUMMARY_USAGE}\n\n{_GATE_SUMMARY_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--item", default=None,
                        help="Target item (PREFIX-N or number).")
    parser.add_argument("--epic-id", dest="epic_id", type=int, default=None,
                        help="Epic id (with --task-num).")
    parser.add_argument("--task-num", dest="task_num", type=int, default=None,
                        help="Task number (with --epic-id).")
    parser.add_argument("--target", required=True,
                        choices=("reviewed-implementation", "implemented"),
                        help="Gate transition to summarize against.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_GATE_SUMMARY_USAGE)
    if parsed is None:
        return 2
    if parsed.item is not None:
        target = item_target("item", parsed.item, parsed.project)
    elif parsed.epic_id is not None and parsed.task_num is not None:
        target = TargetRef(
            kind="epic_task",
            epic_id=int(parsed.epic_id), task_num=int(parsed.task_num),
        )
    else:
        return usage_error(
            "gate-summary requires --item PREFIX-N OR both --epic-id and "
            "--task-num"
        )
    return dispatch_and_emit(
        function_id="qa.gate_summary.run",
        target=target,
        payload={"transition": parsed.target},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_REQUIREMENT_LIST_USAGE", "QA_REQUIREMENT_GET_USAGE",
    "QA_RUN_LIST_USAGE", "QA_RUN_GET_USAGE", "QA_GATE_SUMMARY_USAGE",
    "qa_requirement_list", "qa_requirement_get", "qa_run_list",
    "qa_run_get", "qa_gate_summary",
]
