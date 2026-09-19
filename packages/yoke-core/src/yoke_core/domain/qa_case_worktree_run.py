"""Run a Command-method QA case locally, in the item's own worktree.

The sibling of :mod:`yoke_core.domain.qa_case_ci_run`: same Command
method contract, executed on this machine instead of on the project's CI
workflow. This is the runner for a project that declares no CI
workflow, and the deliberate fallback for offline or local-only
operation.

Heavy invocations queue behind the machine-wide admission slot
(:mod:`yoke_core.tools.gate_admission`), so one full gate runs at a time
per machine.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.qa_case_environment import (
    COMMAND_CASE_BASE_URL_ENV,
    COMMAND_CASE_DEPLOYMENT_MEMBER_ENV,
    COMMAND_CASE_DEPLOYMENT_RUN_ENV,
)

from yoke_core.domain import qa_case_command_stream
from yoke_core.domain import qa_case_budget
from yoke_core.domain import qa_constants
from yoke_core.domain import qa_gate_timeout
from yoke_core.domain import verification_tree_binding
from yoke_core.domain import verification_tree_binding_pytest_startup
from yoke_core.domain import qa_case_execution
from yoke_core.domain import qa_case_tree_binding_scope
from yoke_core.domain.qa_case_execution import QaCaseExecutionError
from yoke_core.domain.qa_method_config_validation import (
    COMMAND_SHELL_CONTRACT,
    looks_like_python_command_body,
)

#: Surface name carried by this runner's tree-binding refusal.
_TREE_BINDING_SURFACE = "qa case run"


def execute_worktree_case(
    case: dict,
    *,
    base_url: str = "",
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    allow_tree_mismatch: bool = False,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Run the case's command in its worktree and record the verdict."""
    config = case["method_config"]
    command = qa_case_execution.required_case_command(case)
    if looks_like_python_command_body(command):
        raise QaCaseExecutionError(COMMAND_SHELL_CONTRACT)
    budget = qa_case_budget.resolve_command_case_budget(
        config,
        explicit_override=timeout_seconds,
    )
    timeout = budget.seconds
    if timeout < 1 or timeout > qa_constants.MAX_CASE_COMMAND_TIMEOUT_SECONDS:
        raise QaCaseExecutionError(
            "Command case timeout_seconds must be between 1 and "
            f"{qa_constants.MAX_CASE_COMMAND_TIMEOUT_SECONDS}"
        )
    checkout = (
        Path(checkout_path).resolve()
        if checkout_path is not None
        else qa_case_execution._execution_checkout(case)
    )
    if not checkout.is_dir():
        raise QaCaseExecutionError(
            f"command execution checkout does not exist: {checkout}"
        )
    # Which tree produced this verdict. Without it a green recorded against
    # the wrong tree reads exactly like a green against the right one;
    # ``head_sha`` additionally pins the commit the run covered, and the
    # binding decision below compares it against the tree this case answers
    # for.
    tree = verification_tree_binding.resolve_tree_identity(checkout)
    # A case whose lane branch has no live worktree falls back to the
    # project checkout, so the gate run can land in main while the
    # session's claimed lane sits untouched. The verdict this produces is
    # recorded, so the refusal belongs before the command, not after. A
    # deployment-run case answers for the candidate its run deployed
    # instead, so that revision is what its checkout is held to.
    if qa_case_tree_binding_scope.session_lane_binds_case(case):
        binding = verification_tree_binding.evaluate_run(
            surface=_TREE_BINDING_SURFACE, tree=str(checkout),
            allow_mismatch=allow_tree_mismatch,
        )
    else:
        binding = qa_case_tree_binding_scope.evaluate_deployment_binding(
            surface=_TREE_BINDING_SURFACE,
            case=case,
            tree=str(checkout),
            head_sha=tree.head_sha if tree else "",
            allow_mismatch=allow_tree_mismatch,
        )
    if binding.notice:
        print(binding.notice, file=sys.stderr, flush=True)
    if binding.refusal:
        raise QaCaseExecutionError(binding.refusal)
    # Already judged above; a pytest-shaped command's startup check
    # inherits that answer instead of repeating the lookup.
    command_env = verification_tree_binding_pytest_startup.with_binding_evaluated(
        os.environ
    )
    if config.get("requires_base_url") and not base_url:
        raise QaCaseExecutionError(
            "this Command case requires --base-url. Pass "
            "`yoke qa case run --requirement-id N --base-url URL` "
            "(or the matching plan-run flag); the runner exports it as "
            "BASE_URL for the command, including a direct run-attached "
            "row that never went through a plan execution target."
        )
    if base_url:
        command_env[COMMAND_CASE_BASE_URL_ENV] = base_url
    # A run-bound case is materialized per run, so a command that names its
    # run or member as a literal is correct exactly once and silently reports
    # on the wrong subject after that. Hand it the pair the row already
    # carries instead.
    for name, value in (
        (
            COMMAND_CASE_DEPLOYMENT_RUN_ENV,
            case.get("deployment_run_id"),
        ),
        (
            COMMAND_CASE_DEPLOYMENT_MEMBER_ENV,
            case.get("deployment_member_ref"),
        ),
    ):
        text = str(value or "").strip()
        if text:
            command_env[name] = text
    process_timeout = qa_gate_timeout.process_timeout_for_command(
        command, timeout, command_env
    )
    started = time.monotonic()
    # Streamed rather than collected: this run IS the gate, so an agent must
    # be able to watch it and read a live capture instead of running the same
    # suite by hand first just to see progress. The stream owner reaps the
    # whole process group, so a timed-out run releases its databases.
    # ``process_timeout`` is None for a command that owns its own budget
    # after gate admission; the watcher then applies no deadline of its own
    # and the command's 124 is what reports the timeout.
    streamed = qa_case_command_stream.stream_command(
        command,
        cwd=str(checkout),
        env=command_env,
        timeout_seconds=process_timeout,
    )
    exit_code = streamed.exit_code
    duration_ms = int((time.monotonic() - started) * 1000)
    verdict = "pass" if exit_code == 0 else "fail"
    # A timeout and a broken branch both land on ``fail``, and a queued gate's
    # capture ends mid-suite with no failures in it. Say which one this was.
    slot_wait_seconds = qa_gate_timeout.announced_slot_wait_seconds(
        streamed.output
    )
    elapsed_compute_seconds = max(
        0.0,
        duration_ms / 1000 - (slot_wait_seconds or 0.0),
    )
    timeout_summary = (
        qa_gate_timeout.timeout_summary(
            timeout,
            slot_wait_seconds,
            elapsed_compute_seconds=elapsed_compute_seconds,
            requirement_id=int(case["requirement_id"]),
        )
        if streamed.timed_out
        else ""
    )
    output = (
        f"$ {command}\n\n[output]\n{streamed.output}\n\n"
        f"[exit_code]\n{exit_code}\n"
    )
    if timeout_summary:
        output += f"\n[timeout]\n{timeout_summary}\n"
    record = {
        "command": command,
        "cwd": str(checkout),
        "exit_code": exit_code,
        "timed_out": streamed.timed_out,
        "output_tail": output[-16000:],
        "verification_tree": tree.as_payload() if tree else None,
        **budget.as_record(),
    }
    if timeout_summary:
        record["timeout_summary"] = timeout_summary
    raw_result = json.dumps(record, sort_keys=True)
    run_id, artifact_id = qa_case_execution.record_command_run(
        case,
        performed_by="worktree_run",
        raw_result=raw_result,
        duration_ms=duration_ms,
        verdict=verdict,
        output=output,
        filename="command-output.txt",
        metadata={
            "case_key": case["case_key"],
            "exit_code": exit_code,
            "timed_out": streamed.timed_out,
        },
        actor=actor,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "run_id": run_id,
        "artifact_id": artifact_id,
        "runner_id": "worktree_run",
        "verdict": verdict,
        "case_outcome": "passed" if verdict == "pass" else "failed",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "output_capture": str(streamed.capture_path),
        "timed_out": streamed.timed_out,
        "timeout_summary": timeout_summary,
        **budget.as_record(),
        "verification_tree": tree.as_payload() if tree else None,
    }


__all__ = ["execute_worktree_case"]
