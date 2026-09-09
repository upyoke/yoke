"""``yoke qa ...`` browser-family flag adapters.

Function ids used by the per-requirement Browser method runner. Execution
enters through ``yoke qa case run --requirement-id``; there is no aggregate
Browser run command:

* ``qa.browser_context.get`` — one Browser method case + freshness row.
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


QA_BROWSER_CONTEXT_GET_USAGE = (
    "yoke qa browser-context get (--item PREFIX-N | --deployment-run RUN-ID) "
    "--requirement-id N --project P "
    "[--expected-branch BRANCH] [--session-id S] [--json]"
)


def qa_browser_context_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser-context get",
        description=QA_BROWSER_CONTEXT_GET_USAGE,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument(
        "--item", help="Target item (PREFIX-N or project-local number)."
    )
    subject.add_argument(
        "--deployment-run",
        dest="deployment_run",
        help="Target deployment run (run-YYYYMMDD-NNN) for a run-scoped case.",
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="Materialized Browser case id.",
    )
    parser.add_argument(
        "--expected-branch",
        dest="expected_branch",
        default=None,
        help="Also return the branch's latest deployed_sha.",
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
    "[--qa-kind KIND] [--verdict V] [--verdict-reason REASON] [--execution-status S] "
    "[--raw-result TEXT] [--duration-ms N] [--session-id S] [--json]"
)


def qa_run_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run add",
        description=QA_RUN_ADD_USAGE,
        epilog=AGENT_UNDETERMINED_HELP,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="Target qa_requirements.id.",
    )
    parser.add_argument(
        "--performed-by",
        dest="performed_by",
        required=True,
        help="Runner that runs the QA check.",
    )
    parser.add_argument(
        "--qa-kind",
        dest="qa_kind",
        default=None,
        help="Must match the requirement's stored kind.",
    )
    parser.add_argument(
        "--verdict", default=None, help="Optional verdict (omitted for started runs)."
    )
    parser.add_argument(
        "--verdict-reason",
        dest="verdict_reason",
        default=None,
        help="Required with undetermined; see evidence rule below.",
    )
    parser.add_argument(
        "--execution-status",
        dest="execution_status",
        default=None,
        help="Optional execution status.",
    )
    parser.add_argument(
        "--raw-result",
        dest="raw_result",
        default=None,
        help="Optional raw output snippet.",
    )
    parser.add_argument(
        "--duration-ms",
        dest="duration_ms",
        type=int,
        default=None,
        help="Optional duration in milliseconds.",
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
        "raw_result",
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
    "[--verdict V] [--verdict-reason REASON] [--execution-status S] [--raw-result TEXT] "
    "[--duration-ms N] [--session-id S] [--json]"
)


def qa_run_complete(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run complete",
        description=QA_RUN_COMPLETE_USAGE,
        epilog=AGENT_UNDETERMINED_HELP,
    )
    parser.add_argument(
        "--requirement-id",
        dest="requirement_id",
        type=int,
        required=True,
        help="The run's owning qa_requirements.id.",
    )
    parser.add_argument(
        "--run-id", dest="run_id", type=int, required=True, help="Target qa_runs.id."
    )
    parser.add_argument(
        "--verdict",
        default=None,
        help="Verdict to set (at least one of verdict/status).",
    )
    parser.add_argument(
        "--verdict-reason",
        dest="verdict_reason",
        default=None,
        help="Required with undetermined; see evidence rule below.",
    )
    parser.add_argument(
        "--execution-status",
        dest="execution_status",
        default=None,
        help="Execution status to set.",
    )
    parser.add_argument(
        "--raw-result",
        dest="raw_result",
        default=None,
        help="Optional raw output snippet.",
    )
    parser.add_argument(
        "--duration-ms",
        dest="duration_ms",
        type=int,
        default=None,
        help="Optional duration in milliseconds.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_COMPLETE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"run_id": int(parsed.run_id)}
    for key in ("verdict", "verdict_reason", "execution_status", "raw_result"):
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
