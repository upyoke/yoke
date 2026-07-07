"""``yoke qa ...`` browser-family flag adapters.

Four function ids in one module — the DB legs of the browser-QA
orchestrator (the orchestration itself is the tool-shaped
``yoke qa browser run`` in :mod:`yoke_cli.commands.qa_browser`):

* ``qa.browser_context.get`` — batched read: browser-kind requirements +
  freshness row for one item.
* ``qa.run.add`` — insert a ``qa_runs`` row (two-phase shape; verdict may
  land later via complete).
* ``qa.run.complete`` — finalize a run in place.
* ``qa.artifact.add`` — insert a ``qa_artifacts`` row (typed handle).
* ``qa.artifact.presign`` — mint a presigned S3 PUT for one artifact.
* ``qa.screenshot_evidence.pending_count`` / ``qa.screenshot_evidence.satisfy``
  — the advance gate's evidence pre-check and bridge.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


QA_BROWSER_CONTEXT_GET_USAGE = (
    "yoke qa browser-context get --item PREFIX-N --project P "
    "[--expected-branch BRANCH] [--session-id S] [--json]"
)


def qa_browser_context_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser-context get",
        description=QA_BROWSER_CONTEXT_GET_USAGE,
    )
    parser.add_argument("--item", required=True,
                        help="Target item (PREFIX-N or project-local number).")
    parser.add_argument("--expected-branch", dest="expected_branch",
                        default=None,
                        help="Also return the branch's latest deployed_sha.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_CONTEXT_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"project": parsed.project or ""}
    if parsed.expected_branch:
        payload["expected_branch"] = parsed.expected_branch
    return dispatch_and_emit(
        function_id="qa.browser_context.get",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_RUN_ADD_USAGE = (
    "yoke qa run add --requirement-id N --executor-type TYPE "
    "[--qa-kind KIND] [--verdict V] [--execution-status S] "
    "[--raw-result TEXT] [--duration-ms N] [--session-id S] [--json]"
)


def qa_run_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run add", description=QA_RUN_ADD_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="Target qa_requirements.id.")
    parser.add_argument("--executor-type", dest="executor_type", required=True,
                        help="Executor that runs the QA check.")
    parser.add_argument("--qa-kind", dest="qa_kind", default=None,
                        help="Must match the requirement's stored kind.")
    parser.add_argument("--verdict", default=None,
                        help="Optional verdict (omitted for started runs).")
    parser.add_argument("--execution-status", dest="execution_status",
                        default=None, help="Optional execution status.")
    parser.add_argument("--raw-result", dest="raw_result", default=None,
                        help="Optional raw output snippet.")
    parser.add_argument("--duration-ms", dest="duration_ms",
                        type=int, default=None,
                        help="Optional duration in milliseconds.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_ADD_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"executor_type": parsed.executor_type}
    for key in ("qa_kind", "verdict", "execution_status", "raw_result"):
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
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_RUN_COMPLETE_USAGE = (
    "yoke qa run complete --requirement-id N --run-id N "
    "[--verdict V] [--execution-status S] [--raw-result TEXT] "
    "[--duration-ms N] [--session-id S] [--json]"
)


def qa_run_complete(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa run complete", description=QA_RUN_COMPLETE_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="The run's owning qa_requirements.id.")
    parser.add_argument("--run-id", dest="run_id", type=int, required=True,
                        help="Target qa_runs.id.")
    parser.add_argument("--verdict", default=None,
                        help="Verdict to set (at least one of verdict/status).")
    parser.add_argument("--execution-status", dest="execution_status",
                        default=None, help="Execution status to set.")
    parser.add_argument("--raw-result", dest="raw_result", default=None,
                        help="Optional raw output snippet.")
    parser.add_argument("--duration-ms", dest="duration_ms",
                        type=int, default=None,
                        help="Optional duration in milliseconds.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_RUN_COMPLETE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"run_id": int(parsed.run_id)}
    for key in ("verdict", "execution_status", "raw_result"):
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
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_ARTIFACT_ADD_USAGE = (
    "yoke qa artifact add --requirement-id N --run-id N "
    "--artifact-type TYPE --artifact-handle JSON [--content-type CT] "
    "[--metadata JSON] [--session-id S] [--json]"
)


def qa_artifact_add(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa artifact add", description=QA_ARTIFACT_ADD_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="The run's owning qa_requirements.id.")
    parser.add_argument("--run-id", dest="run_id", type=int, required=True,
                        help="Owning qa_runs.id.")
    parser.add_argument("--artifact-type", dest="artifact_type", required=True,
                        help="Artifact type (e.g. screenshot).")
    parser.add_argument("--content-type", dest="content_type", default=None,
                        help="MIME content type (e.g. image/png).")
    parser.add_argument(
        "--artifact-handle", dest="artifact_handle", required=True,
        help=(
            "Typed handle JSON naming where the evidence lives: "
            "{\"backend\":\"s3\",\"bucket\":B,\"key\":K} for uploaded "
            "evidence, {\"backend\":\"local\",\"path\":P} for explicit "
            "machine-local evidence. Bare paths are refused."
        ),
    )
    parser.add_argument("--metadata", default=None,
                        help="Optional metadata JSON string.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_ADD_USAGE)
    if parsed is None:
        return 2
    try:
        handle = json.loads(parsed.artifact_handle)
    except json.JSONDecodeError as exc:
        print(
            f"yoke qa artifact add: --artifact-handle is not valid JSON "
            f"({exc}); pass a typed handle object, not a bare path.",
        )
        return 2
    payload: Dict[str, Any] = {
        "run_id": int(parsed.run_id),
        "artifact_type": parsed.artifact_type,
        "artifact_handle": handle,
    }
    for key in ("content_type", "metadata"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    return dispatch_and_emit(
        function_id="qa.artifact.add",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_ARTIFACT_PRESIGN_USAGE = (
    "yoke qa artifact presign --requirement-id N --run-id N "
    "--filename NAME [--content-type CT] [--session-id S] [--json]"
)


def qa_artifact_presign(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa artifact presign",
        description=QA_ARTIFACT_PRESIGN_USAGE,
    )
    parser.add_argument("--requirement-id", dest="requirement_id",
                        type=int, required=True,
                        help="The run's owning qa_requirements.id.")
    parser.add_argument("--run-id", dest="run_id", type=int, required=True,
                        help="Owning qa_runs.id (keys the S3 object).")
    parser.add_argument("--filename", required=True,
                        help="Artifact filename (single path segment).")
    parser.add_argument("--content-type", dest="content_type", default=None,
                        help="MIME content type for the upload (e.g. image/png).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_ARTIFACT_PRESIGN_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "run_id": int(parsed.run_id),
        "filename": parsed.filename,
    }
    if parsed.content_type is not None:
        payload["content_type"] = parsed.content_type
    return dispatch_and_emit(
        function_id="qa.artifact.presign",
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(parsed.requirement_id),
        ),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE = (
    "yoke qa screenshot-evidence pending-count --item PREFIX-N "
    "[--session-id S] [--json]"
)


def qa_screenshot_evidence_pending_count(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa screenshot-evidence pending-count",
        description=QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE,
    )
    parser.add_argument("--item", required=True,
                        help="Target item (PREFIX-N or project-local number).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE,
    )
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="qa.screenshot_evidence.pending_count",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE = (
    "yoke qa screenshot-evidence satisfy --item PREFIX-N "
    "[--evidence TEXT] [--session-id S] [--json]"
)


def qa_screenshot_evidence_satisfy(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa screenshot-evidence satisfy",
        description=QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE,
    )
    parser.add_argument("--item", required=True,
                        help="Target item (PREFIX-N or project-local number).")
    parser.add_argument("--evidence", default=None,
                        help="Evidence text recorded on the bridged runs.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.evidence is not None:
        payload["evidence"] = parsed.evidence
    return dispatch_and_emit(
        function_id="qa.screenshot_evidence.satisfy",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


__all__ = [
    "QA_BROWSER_CONTEXT_GET_USAGE", "QA_RUN_ADD_USAGE",
    "QA_RUN_COMPLETE_USAGE", "QA_ARTIFACT_ADD_USAGE",
    "QA_ARTIFACT_PRESIGN_USAGE",
    "QA_SCREENSHOT_EVIDENCE_PENDING_COUNT_USAGE",
    "QA_SCREENSHOT_EVIDENCE_SATISFY_USAGE",
    "qa_browser_context_get", "qa_run_add", "qa_run_complete",
    "qa_artifact_add", "qa_artifact_presign",
    "qa_screenshot_evidence_pending_count",
    "qa_screenshot_evidence_satisfy",
]
