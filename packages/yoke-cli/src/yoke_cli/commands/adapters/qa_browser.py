"""``yoke qa ...`` browser-family flag adapters.

Function ids used by the per-requirement Browser method runner. Execution
enters through ``yoke qa case run --requirement-id``; there is no aggregate
Browser run command:

* ``qa.browser_context.get`` — one Browser method case plus whichever
  deployment it is about (named persistent environment or branch preview).
* ``qa.run.add`` — insert a ``qa_runs`` row (two-phase shape; verdict may
  land later via complete).
* ``qa.run.complete`` — finalize a run in place.

Artifact add/presign live in ``qa_artifact_cli``.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.qa_artifact_cli import (
    QA_ARTIFACT_ADD_USAGE,
    QA_ARTIFACT_PRESIGN_USAGE,
    qa_artifact_add,
    qa_artifact_presign,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.qa_execution_status import (
    EXECUTION_STATUS_HELP,
    EXECUTION_STATUS_USAGE_TOKEN,
    VALID_EXECUTION_STATUSES,
)


QA_BROWSER_CONTEXT_GET_USAGE = (
    "yoke qa browser-context get (--item PREFIX-N | --deployment-run RUN-ID) "
    "--requirement-id N --project P "
    "[--expected-branch BRANCH] [--full] [--session-id S] [--json]"
)


def qa_browser_context_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser-context get",
        usage=QA_BROWSER_CONTEXT_GET_USAGE,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item", metavar="PREFIX-N", help="Item the case belongs to.")
    subject.add_argument(
        "--deployment-run",
        dest="deployment_run",
        metavar="RUN-ID",
        help="Deployment run (run-YYYYMMDD-NNN) the case belongs to.",
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id of the Browser case.",
    )
    parser.add_argument(
        "--expected-branch",
        dest="expected_branch",
        default=None,
        metavar="BRANCH",
        help="Also return this branch's latest deployed commit (deployed_sha).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_CONTEXT_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "project": parsed.project or "",
        "requirement_id": parsed.requirement_id,
    }
    if parsed.expected_branch:
        payload["expected_branch"] = parsed.expected_branch
    target = (
        item_target("item", parsed.item, parsed.project)
        if parsed.item
        else TargetRef(
            kind="deployment_run",
            deployment_run_id=str(parsed.deployment_run),
            project_id=client_project_context(parsed.project),
        )
    )
    return dispatch_and_emit(
        function_id="qa.browser_context.get",
        target=target,
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


AGENT_UNDETERMINED_HELP = (
    "Agent undetermined halts the item for owner/operator evidence review. "
    "Start the run, attach evidence with `yoke qa artifact add`, then complete "
    "it; use error when the attempt produced no evidence."
)


QA_RUN_ADD_USAGE = (
    "yoke qa run add --requirement-id N --performed-by TYPE "
    "[--qa-kind KIND] [--verdict V] [--verdict-reason REASON] "
    f"[--execution-status {EXECUTION_STATUS_USAGE_TOKEN}] "
    "[--capture-degraded-reason TEXT] "
    "[--raw-result TEXT] [--head-sha SHA] [--duration-ms N] [--session-id S] [--json]"
)


def qa_run_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run add",
        usage=QA_RUN_ADD_USAGE,
        epilog=AGENT_UNDETERMINED_HELP,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id the run belongs to.",
    )
    parser.add_argument(
        "--performed-by",
        dest="performed_by",
        required=True,
        metavar="TYPE",
        help=(
            "Who ran the check, e.g. agent, browser_substrate, host_control, "
            "agent_mission. Browser cases refuse agent."
        ),
    )
    parser.add_argument(
        "--qa-kind",
        dest="qa_kind",
        default=None,
        metavar="KIND",
        help="QA kind; when given it must match the requirement's kind.",
    )
    parser.add_argument(
        "--verdict",
        default=None,
        metavar="V",
        help="Verdict: pass, fail, undetermined, or error. Omit it to start a run.",
    )
    parser.add_argument(
        "--verdict-reason",
        dest="verdict_reason",
        default=None,
        metavar="REASON",
        help="Why the result is undetermined; required with that verdict.",
    )
    parser.add_argument(
        "--execution-status",
        dest="execution_status",
        choices=VALID_EXECUTION_STATUSES,
        default=None,
        metavar=EXECUTION_STATUS_USAGE_TOKEN,
        help=EXECUTION_STATUS_HELP,
    )
    parser.add_argument(
        "--capture-degraded-reason",
        dest="capture_degraded_reason",
        default=None,
        metavar="TEXT",
        help="Why a captured run has no attached evidence files.",
    )
    parser.add_argument(
        "--raw-result",
        dest="raw_result",
        default=None,
        metavar="TEXT",
        help="Short raw output from the check.",
    )
    parser.add_argument(
        "--duration-ms",
        dest="duration_ms",
        type=int,
        default=None,
        metavar="N",
        help="How long the check took, in milliseconds.",
    )
    parser.add_argument(
        "--head-sha", metavar="SHA", help="Full commit SHA this evidence verifies."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_ADD_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"performed_by": parsed.performed_by}
    for key in (
        "qa_kind",
        "verdict",
        "verdict_reason",
        "execution_status",
        "capture_degraded_reason",
        "raw_result",
        "head_sha",
    ):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.duration_ms is not None:
        payload["duration_ms"] = int(parsed.duration_ms)
    return dispatch_and_emit(
        function_id="qa.run.add",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


QA_RUN_COMPLETE_USAGE = (
    "yoke qa run complete --requirement-id N --run-id N "
    "[--verdict V] [--verdict-reason REASON] "
    f"[--execution-status {EXECUTION_STATUS_USAGE_TOKEN}] "
    "[--capture-degraded-reason TEXT] [--raw-result TEXT] "
    "[--duration-ms N] [--session-id S] [--json]"
)


def qa_run_complete(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run complete",
        usage=QA_RUN_COMPLETE_USAGE,
        epilog=AGENT_UNDETERMINED_HELP,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        metavar="N",
        help="QA requirement id the run belongs to.",
    )
    parser.add_argument(
        "--run-id", dest="run_id", type=int, required=True, metavar="N",
        help="Id of the started QA run to complete.",
    )
    parser.add_argument(
        "--verdict",
        default=None,
        metavar="V",
        help="Verdict: pass, fail, undetermined, or error. Give it, --execution-status, or both.",
    )
    parser.add_argument(
        "--verdict-reason",
        dest="verdict_reason",
        default=None,
        metavar="REASON",
        help="Why the result is undetermined; required with that verdict.",
    )
    parser.add_argument(
        "--execution-status",
        dest="execution_status",
        choices=VALID_EXECUTION_STATUSES,
        default=None,
        metavar=EXECUTION_STATUS_USAGE_TOKEN,
        help=EXECUTION_STATUS_HELP,
    )
    parser.add_argument(
        "--capture-degraded-reason",
        dest="capture_degraded_reason",
        default=None,
        metavar="TEXT",
        help="Why a captured run has no attached evidence files.",
    )
    parser.add_argument(
        "--raw-result",
        dest="raw_result",
        default=None,
        metavar="TEXT",
        help="Short raw output from the check.",
    )
    parser.add_argument(
        "--duration-ms",
        dest="duration_ms",
        type=int,
        default=None,
        metavar="N",
        help="How long the check took, in milliseconds.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_COMPLETE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"run_id": int(parsed.run_id)}
    for key in (
        "verdict",
        "verdict_reason",
        "execution_status",
        "capture_degraded_reason",
        "raw_result",
    ):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    if parsed.duration_ms is not None:
        payload["duration_ms"] = int(parsed.duration_ms)
    return dispatch_and_emit(
        function_id="qa.run.complete",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "AGENT_UNDETERMINED_HELP",
    "QA_BROWSER_CONTEXT_GET_USAGE",
    "QA_RUN_ADD_USAGE",
    "QA_RUN_COMPLETE_USAGE",
    "QA_ARTIFACT_ADD_USAGE",
    "QA_ARTIFACT_PRESIGN_USAGE",
    "qa_browser_context_get",
    "qa_run_add",
    "qa_run_complete",
    "qa_artifact_add",
    "qa_artifact_presign",
]
