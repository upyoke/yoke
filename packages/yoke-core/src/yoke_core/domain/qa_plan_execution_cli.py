"""Engine-owned CLI for ordered materialized QA plan execution."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from typing import Any, List, Optional

from yoke_core.domain.qa_case_execution_cli import WAITING_RETRY_EXIT
from yoke_core.domain.qa_plan_execution import (
    QaPlanExecutionError,
    execute_plan,
)

AGENT_REVIEW_REQUIRED_EXIT = 12

#: Result fields restated on stderr for a case that did not pass, as
#: ``label=value`` pairs after the requirement id.
_REPORTED_CASE_FIELDS = (
    ("case", "case_key"),
    ("outcome", "case_outcome"),
    ("verdict", "verdict"),
    ("exit_code", "exit_code"),
    ("error", "error"),
)


def _report_case_failures(result: dict[str, Any]) -> None:
    """Restate every case that did not pass, one line each, on stderr.

    A plan run ends on a single JSON document covering many cases, and the
    case that actually stopped the run is one entry inside it. The reader
    of the terminal gets the same treatment ``yoke qa case run`` gives its
    single verdict: which requirement, which case, and why — without
    parsing stdout or re-running the plan to find out.
    """
    from yoke_core.domain.qa_plan_execution_result_state import aggregate_state

    for case in result.get("results") or []:
        if not isinstance(case, dict) or aggregate_state("passed", case) == "passed":
            continue
        fields = [f"requirement={case.get('requirement_id')}"]
        fields.extend(
            f"{label}={case[key]}"
            for label, key in _REPORTED_CASE_FIELDS
            if case.get(key) not in (None, "")
        )
        print(f"# qa plan run: {' '.join(fields)}", file=sys.stderr, flush=True)


def _review_connection_env() -> str:
    explicit = os.environ.get("YOKE_ENV", "").strip()
    if explicit:
        return explicit
    from yoke_contracts.machine_config.runtime import active_env

    return active_env()


def _qualify_review_dispatch(result: dict[str, Any]) -> None:
    bundle = result.get("review_bundle")
    if not isinstance(bundle, dict):
        return
    dispatch = bundle.get("dispatch")
    if not isinstance(dispatch, dict):
        raise QaPlanExecutionError("QA review bundle lacks a dispatch contract")
    authority = dispatch.get("authority")
    if not isinstance(authority, dict) or authority.get("state") != "bound":
        raise QaPlanExecutionError("QA review bundle lacks immutable target authority")
    connection_env = _review_connection_env()
    authority["connection_env"] = connection_env
    prefix = f"yoke --env {shlex.quote(connection_env)}"
    commands = dispatch.get("artifact_read_commands")
    if not isinstance(commands, list) or any(
        not isinstance(command, str) or not command.startswith("yoke ")
        for command in commands
    ):
        raise QaPlanExecutionError(
            "QA review bundle lacks typed artifact-read commands"
        )
    dispatch["artifact_read_commands"] = [
        command.replace("yoke ", f"{prefix} ", 1) for command in commands
    ]
    walkers = dispatch.get("walker_dispatches") or []
    if not isinstance(walkers, list):
        raise QaPlanExecutionError("QA review bundle has invalid walker dispatches")
    for walker in walkers:
        if not isinstance(walker, dict):
            raise QaPlanExecutionError("QA mission walker is not an object")
        for key in (
            "host_command",
            "browser_setup_command",
            "browser_step_command",
            "artifact_add_command",
        ):
            command = walker.get(key)
            if not isinstance(command, str) or not command.startswith("yoke "):
                label = key.replace("_", "-")
                raise QaPlanExecutionError(
                    f"QA mission walker lacks a typed {label}"
                )
            qualified = command.replace("yoke ", f"{prefix} ", 1)
            walker[key] = qualified
            walker["prompt"] = str(walker.get("prompt") or "").replace(
                command,
                qualified,
            )
    submit = dispatch.get("submit_command")
    if not isinstance(submit, str) or not submit.startswith("yoke "):
        raise QaPlanExecutionError(
            "QA review bundle lacks a typed verdict submission command"
        )
    dispatch["submit_command"] = submit.replace("yoke ", f"{prefix} ", 1)
    dispatch["prompt"] = (
        f"{str(dispatch.get('prompt') or '').strip()} Use the exact Yoke "
        f"connection `{connection_env}` carried by this handoff for every "
        "registered read and submission; do not use the ambient connection."
    )


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan run",
        description=(
            "Execute a materialized transition's cases in immutable "
            "plan/case/baseline order through their registered runners."
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
    parser.add_argument(
        "--allow-tree-mismatch",
        action="store_true",
        help=(
            "Run the roster's cases against the resolved checkout even when "
            "it sits outside this session's claim-bound worktree."
        ),
    )
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
            public_ref=parsed.item,
            transition_id=parsed.transition,
            deployment_run_id=parsed.deployment_run_id,
            plan=parsed.plan,
            project=parsed.project,
            base_url=parsed.base_url,
            expected_branch=parsed.expected_branch,
            expected_sha=parsed.expected_sha,
            timeout_seconds=parsed.timeout_seconds,
            allow_tree_mismatch=parsed.allow_tree_mismatch,
            actor=actor,
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan run: {exc}", file=sys.stderr)
        return 2
    if result.get("state") == "awaiting_agent_review":
        try:
            _qualify_review_dispatch(result)
        except QaPlanExecutionError as exc:
            print(f"yoke qa plan run: {exc}", file=sys.stderr)
            return 2
    _report_case_failures(result)
    print(json.dumps(result, sort_keys=True))
    state = result.get("state")
    if state == "waiting":
        return WAITING_RETRY_EXIT
    if state == "awaiting_agent_review":
        print(
            "QA capture complete; dispatch the returned typed reviewer contract "
            "now and submit its complete verdict batch before continuing.",
            file=sys.stderr,
        )
        return AGENT_REVIEW_REQUIRED_EXIT
    if state in {"failed", "needs_review", "blocked_on_precondition"}:
        return 1
    if state == "error":
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["AGENT_REVIEW_REQUIRED_EXIT", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
