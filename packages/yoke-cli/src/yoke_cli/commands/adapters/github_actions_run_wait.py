"""Client-side wait wrapper for arbitrary GitHub Actions run ids."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Optional

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import FunctionCallResponse, TargetRef


GITHUB_ACTIONS_WAIT_RUN_USAGE = (
    "yoke github-actions wait-run <repo-slug> <run-id> "
    "[--timeout SEC] [--project P] [--session-id S] [--json]"
)
RUN_WAIT_POLL_INTERVAL_SEC = 15

now = time.time
sleep = time.sleep


def github_actions_wait_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions wait-run",
        description=(
            "Wait for one GitHub Actions run to complete. The polling loop "
            "runs client-side; each poll dispatches the single-shot "
            "github_actions.wait_run read, so long waits are safe over HTTPS."
        ),
    )
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/yoke.")
    parser.add_argument("run_id", help="GitHub Actions run id.")
    parser.add_argument(
        "--timeout", type=int, default=1800, dest="timeout_sec", metavar="SEC",
        help="Wait budget in seconds (default: 1800).",
    )
    parser.add_argument(
        "--project", default="yoke",
        help="Project capability owning the GitHub App repo binding (default: yoke).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_WAIT_RUN_USAGE)
    if parsed is None:
        return 2
    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    return wait_for_run_completion(
        {
            "repo": parsed.repo,
            "run_id": parsed.run_id,
            "project": parsed.project,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        timeout_sec=max(0, parsed.timeout_sec),
    )


def wait_for_run_completion(
    payload: Dict[str, Any],
    *,
    session_id: Optional[str],
    json_mode: bool,
    timeout_sec: int,
) -> int:
    ensure_handlers_loaded()
    actor = build_actor(session_id=session_id)
    start = now()
    while True:
        response = call_dispatcher(
            function_id="github_actions.wait_run",
            target=TargetRef(kind="global"),
            payload=dict(payload),
            actor=actor,
        )
        if not response.success:
            return emit_response(response, json_mode=json_mode)

        result = response.result or {}
        state = str(result.get("state") or "")
        if state in {"success", "failed"}:
            return _emit_terminal(response, json_mode=json_mode)

        elapsed = int(now() - start)
        if elapsed >= timeout_sec:
            return _emit_timeout(response, json_mode=json_mode)

        print(
            f"  Run status: {result.get('message') or state or 'running'} "
            f"(elapsed: {elapsed}s, timeout: {timeout_sec}s)",
            file=sys.stderr,
        )
        sleep(RUN_WAIT_POLL_INTERVAL_SEC)


def _emit_terminal(response: FunctionCallResponse, *, json_mode: bool) -> int:
    result = response.result or {}
    exit_code = 0 if result.get("state") == "success" else 1
    if json_mode:
        emit_response(response, json_mode=True)
    else:
        print(result.get("message") or result.get("state") or "")
    return exit_code


def _emit_timeout(response: FunctionCallResponse, *, json_mode: bool) -> int:
    result = dict(response.result or {})
    message = f"timeout:{result.get('message') or result.get('state') or 'running'}"
    timed_out = response.model_copy(
        update={"result": {**result, "state": "timeout", "message": message}},
    )
    if json_mode:
        emit_response(timed_out, json_mode=True)
    else:
        print(message)
    return 3


__all__ = [
    "GITHUB_ACTIONS_WAIT_RUN_USAGE",
    "RUN_WAIT_POLL_INTERVAL_SEC",
    "github_actions_wait_run",
    "wait_for_run_completion",
]
