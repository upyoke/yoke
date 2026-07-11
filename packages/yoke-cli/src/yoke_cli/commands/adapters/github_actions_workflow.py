"""Point-in-time GitHub Actions workflow adapters for deploy orchestration."""

from __future__ import annotations

import argparse
import os
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)


GITHUB_ACTIONS_TRIGGER_USAGE = (
    "yoke github-actions trigger <repo-slug> <workflow-file> "
    "[--ref REF] [--input KEY=VALUE] --request-id ID "
    "--correlation-input yoke_dispatch_id --project P "
    "[--session-id S] [--json]"
)
GITHUB_ACTIONS_TRIGGER_ONCE_USAGE = (
    "yoke github-actions trigger-once <repo-slug> <workflow-file> "
    "[--ref REF] [--input KEY=VALUE] --project P [--session-id S] [--json]"
)
GITHUB_ACTIONS_FIND_RUN_USAGE = (
    "yoke github-actions find-run <repo-slug> <workflow-file> <commit-sha> "
    "--project P [--session-id S] [--json]"
)
GITHUB_ACTIONS_POLL_USAGE = (
    "yoke github-actions poll <repo-slug> <run-id> "
    "--project P [--session-id S] [--json]"
)
GITHUB_ACTIONS_JOBS_COUNT_USAGE = (
    "yoke github-actions jobs-count <repo-slug> <run-id> [--attempt N] "
    "--project P [--session-id S] [--json]"
)

# Point-in-time workflow state uses 0=success, 1=workflow failure/not-found,
# 2=waiting, and 3=running. Hosted dispatcher/transport failures must stay
# outside that state vocabulary so deploy polling retries them instead of
# declaring that the workflow itself failed.
GITHUB_ACTIONS_OPERATION_ERROR_EXIT = 4


def _add_common(parser: argparse.ArgumentParser, *, run_id: bool = False) -> None:
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/platform.")
    if run_id:
        parser.add_argument("run_id", help="GitHub Actions workflow run id.")
    parser.add_argument(
        "--project",
        required=True,
        help="Project capability owning the GitHub App repo binding.",
    )
    add_session_arg(parser)
    add_json_arg(parser)


def _call(
    function_id: str,
    payload: Dict[str, Any],
    *,
    session_id: str | None,
    request_id: str | None = None,
) -> FunctionCallResponse:
    ensure_handlers_loaded()
    local_setting = os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip()
    if local_setting not in ("", "1"):
        return _authority_error(
            function_id,
            request_id,
            f"{GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV} must be 1 when set",
        )
    local_dispatch = None
    if local_setting == "1":
        from yoke_core.domain.github_actions_local_authority import dispatch

        local_dispatch = dispatch
    else:
        try:
            from yoke_cli.transport.https import resolve_https_connection

            https = resolve_https_connection()
        except Exception as exc:
            return _authority_error(function_id, request_id, str(exc))
        if https is None:
            return _authority_error(
                function_id,
                request_id,
                "GitHub Actions requires an HTTPS control-plane connection or "
                f"{GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV}=1 for attended bootstrap",
            )
    return call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=session_id),
        request_id=request_id,
        local_only=local_dispatch is not None,
        _local_dispatch=local_dispatch,
    )


def _authority_error(
    function_id: str,
    request_id: str | None,
    message: str,
) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=False,
        function=function_id,
        version="v1",
        request_id=request_id,
        error=FunctionError(code="github_actions_authority_required", message=message),
    )


def _valid_repo(repo: str) -> bool:
    return "/" in repo


def _emit_operation_error(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
) -> int:
    emit_response(response, json_mode=json_mode)
    return GITHUB_ACTIONS_OPERATION_ERROR_EXIT


def github_actions_trigger(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions trigger",
        description=(
            "Dispatch one workflow and return its exact run id through the "
            "project's GitHub App authority."
        ),
    )
    parser.add_argument("repo")
    parser.add_argument("workflow")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--input", action="append", dest="inputs", default=[])
    parser.add_argument(
        "--request-id",
        required=True,
        help="Stable idempotency key for one logical workflow dispatch.",
    )
    parser.add_argument(
        "--correlation-input",
        required=True,
        choices=(WORKFLOW_DISPATCH_CORRELATION_INPUT,),
        help="Declared workflow input used for GitHub-visible recovery.",
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_TRIGGER_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    inputs: Dict[str, str] = {}
    for raw in parsed.inputs:
        key, separator, value = str(raw).partition("=")
        if not separator or not key:
            return usage_error(f"--input must be KEY=VALUE, got {raw!r}")
        inputs[key] = value
    response = _call(
        "github_actions.workflow.dispatch",
        {
            "repo": parsed.repo,
            "workflow": parsed.workflow,
            "ref": parsed.ref,
            "inputs": inputs,
            "project": parsed.project,
            "correlation_input": parsed.correlation_input,
        },
        session_id=parsed.session_id,
        request_id=parsed.request_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    if parsed.json_mode:
        return emit_response(response, json_mode=parsed.json_mode)
    print(response.result.get("run_id") or "")
    return 0


def github_actions_trigger_once(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions trigger-once",
        description=(
            "Dispatch one correlation-unaware workflow exactly once. A lost "
            "response is reported as ambiguous and is never retried."
        ),
    )
    parser.add_argument("repo")
    parser.add_argument("workflow")
    parser.add_argument("--ref", default="main")
    parser.add_argument("--input", action="append", dest="inputs", default=[])
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_TRIGGER_ONCE_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    inputs: Dict[str, str] = {}
    for raw in parsed.inputs:
        key, separator, value = str(raw).partition("=")
        if not separator or not key:
            return usage_error(f"--input must be KEY=VALUE, got {raw!r}")
        inputs[key] = value
    response = _call(
        "github_actions.workflow.dispatch_once",
        {
            "repo": parsed.repo,
            "workflow": parsed.workflow,
            "ref": parsed.ref,
            "inputs": inputs,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    if parsed.json_mode:
        return emit_response(response, json_mode=True)
    print(response.result.get("run_id") or "")
    return 0


def github_actions_find_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github-actions find-run")
    parser.add_argument("repo")
    parser.add_argument("workflow")
    parser.add_argument("commit_sha")
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_FIND_RUN_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    response = _call(
        "github_actions.workflow.find_run",
        {
            "repo": parsed.repo,
            "workflow": parsed.workflow,
            "head_sha": parsed.commit_sha,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    found = bool(response.result.get("found"))
    if parsed.json_mode:
        emit_response(response, json_mode=True)
    else:
        print(response.result.get("run_id") if found else "not_found")
    return 0 if found else 1


def github_actions_poll(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github-actions poll")
    _add_common(parser, run_id=True)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_POLL_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    response = _call(
        "github_actions.wait_run",
        {
            "repo": parsed.repo,
            "run_id": parsed.run_id,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    state = str(response.result.get("state") or "")
    if parsed.json_mode:
        emit_response(response, json_mode=True)
    else:
        print(response.result.get("message") or state)
    return {"success": 0, "failed": 1, "waiting": 2, "running": 3}.get(
        state, 1
    )


def github_actions_jobs_count(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github-actions jobs-count")
    _add_common(parser, run_id=True)
    parser.add_argument("--attempt", type=int, default=1)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_JOBS_COUNT_USAGE)
    if parsed is None:
        return 2
    if not _valid_repo(parsed.repo):
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")
    response = _call(
        "github_actions.run.jobs_count",
        {
            "repo": parsed.repo,
            "run_id": parsed.run_id,
            "attempt": parsed.attempt,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
    )
    if not response.success:
        return _emit_operation_error(response, json_mode=parsed.json_mode)
    if parsed.json_mode:
        return emit_response(response, json_mode=parsed.json_mode)
    print(response.result.get("count", 0))
    return 0


__all__ = [
    "GITHUB_ACTIONS_FIND_RUN_USAGE",
    "GITHUB_ACTIONS_JOBS_COUNT_USAGE",
    "GITHUB_ACTIONS_OPERATION_ERROR_EXIT",
    "GITHUB_ACTIONS_POLL_USAGE",
    "GITHUB_ACTIONS_TRIGGER_USAGE",
    "GITHUB_ACTIONS_TRIGGER_ONCE_USAGE",
    "github_actions_find_run",
    "github_actions_jobs_count",
    "github_actions_poll",
    "github_actions_trigger",
    "github_actions_trigger_once",
]
