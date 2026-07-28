"""Engine-owned CLI for ordered materialized QA plan execution."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from yoke_core.domain.qa_case_execution_cli import WAITING_RETRY_EXIT
from yoke_core.domain.qa_plan_execution import (
    QaPlanExecutionError,
    execute_plan,
)


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan run",
        description=(
            "Execute a materialized transition's cases in immutable "
            "plan/case/baseline order through their registered executors."
        ),
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--transition")
    parser.add_argument("--plan")
    parser.add_argument("--project")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-sha")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)
    if bool(parsed.expected_branch) != bool(parsed.expected_sha):
        parser.error("--expected-branch and --expected-sha must be paired")
    if parsed.item and not parsed.transition:
        parser.error("--item requires --transition")
    if parsed.item and parsed.plan:
        parser.error("--item uses attached plans and does not accept --plan")
    if parsed.deployment_run_id and not parsed.plan:
        parser.error("--deployment-run-id requires --plan")
    if parsed.deployment_run_id and parsed.transition:
        parser.error("--deployment-run-id does not accept --transition")
    if parsed.deployment_run_id and not parsed.project:
        parser.error("--deployment-run-id requires --project")

    from yoke_core.api.service_client_structured_api_adapter import build_actor

    actor = build_actor(session_id=parsed.session_id)
    try:
        result = execute_plan(
            item_ref=parsed.item,
            transition_id=parsed.transition,
            deployment_run_id=parsed.deployment_run_id,
            plan=parsed.plan,
            project=parsed.project,
            base_url=parsed.base_url,
            expected_branch=parsed.expected_branch,
            expected_sha=parsed.expected_sha,
            timeout_seconds=parsed.timeout_seconds,
            actor=actor,
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan run: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    state = result.get("state")
    if state == "waiting":
        return WAITING_RETRY_EXIT
    if state in {"failed", "needs_review", "blocked_on_precondition"}:
        return 1
    if state == "error":
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
