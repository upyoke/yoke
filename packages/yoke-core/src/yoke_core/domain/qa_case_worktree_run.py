"""Run a Command-method QA case locally, in the item's own worktree.

The sibling of :mod:`yoke_core.domain.qa_case_ci_run`: same Command
method contract, executed on this machine instead of on the project's CI
workflow. This is the executor for a project that declares no CI
workflow, and the deliberate fallback for offline or local-only
operation.

Heavy invocations queue behind the machine-wide admission slot
(:mod:`yoke_core.tools.gate_admission`), so one full gate runs at a time
per machine.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from yoke_contracts.api.function_call import ActorContext

from yoke_core.domain import qa_case_command_stream
from yoke_core.domain import test_gate_timeout
from yoke_core.domain import verification_tree_binding
from yoke_core.domain import qa_case_execution
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

#: Surface name carried by this executor's tree-binding refusal.
_TREE_BINDING_SURFACE = "qa case run"


def execute_worktree_case(
    case: dict,
    *,
    base_url: str = "",
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Run the case's command in its worktree and record the verdict."""
    config = case["method_config"]
    command = str(config.get("command") or "").strip()
    if not command:
        raise QaCaseExecutionError("Command case requires method_config.command")
    configured_timeout = config.get("timeout_seconds", 1200)
    timeout = int(
        timeout_seconds if timeout_seconds is not None else configured_timeout
    )
    if timeout < 1 or timeout > 7200:
        raise QaCaseExecutionError(
            "Command case timeout_seconds must be between 1 and 7200"
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
    # A case whose lane branch has no live worktree falls back to the
    # project checkout, so the gate run can land in main while the
    # session's claimed lane sits untouched. The verdict this produces is
    # recorded, so the refusal belongs before the command, not after.
    binding_refusal = verification_tree_binding.check(
        surface=_TREE_BINDING_SURFACE, tree=str(checkout),
    )
    if binding_refusal is not None:
        raise QaCaseExecutionError(binding_refusal)
    command_env = dict(os.environ)
    if config.get("requires_base_url"):
        if not base_url:
            raise QaCaseExecutionError("this Command case requires --base-url")
        command_env["BASE_URL"] = base_url
    process_timeout = test_gate_timeout.process_timeout_for_command(
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
    timeout_summary = (
        test_gate_timeout.timeout_summary(
            timeout,
            test_gate_timeout.announced_slot_wait_seconds(streamed.output),
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
    # Which tree produced this verdict. Without it a green recorded
    # against the wrong tree reads exactly like a green against the right
    # one; ``head_sha`` additionally pins the commit the run covered.
    tree = verification_tree_binding.resolve_tree_identity(checkout)
    record = {
        "command": command,
        "cwd": str(checkout),
        "exit_code": exit_code,
        "timed_out": streamed.timed_out,
        "output_tail": output[-16000:],
        "verification_tree": tree.as_payload() if tree else None,
    }
    if timeout_summary:
        record["timeout_summary"] = timeout_summary
    raw_result = json.dumps(record, sort_keys=True)
    run = qa_case_execution._dispatch(
        "qa.run.add",
        int(case["requirement_id"]),
        {
            "executor_type": "worktree_run",
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
        actor=actor,
    )
    run_id = int(run["qa_run_id"])
    from yoke_core.domain.qa_artifact_handle import local_handle
    from yoke_core.domain.qa_artifacts import (
        artifact_file_path,
        case_artifact_subject,
    )

    output_path = artifact_file_path(
        str(case["project"]),
        case_artifact_subject(case),
        run_id,
        "command-output.txt",
    )
    output_path.write_text(output, encoding="utf-8")
    artifact = qa_case_execution._dispatch(
        "qa.artifact.add",
        int(case["requirement_id"]),
        {
            "run_id": run_id,
            "artifact_type": "command_output",
            "content_type": "text/plain",
            "artifact_handle": local_handle(
                str(output_path.resolve()),
                "text/plain",
            ),
            "metadata": json.dumps(
                {
                    "case_key": case["case_key"],
                    "exit_code": exit_code,
                    "timed_out": streamed.timed_out,
                },
                sort_keys=True,
            ),
        },
        actor=actor,
    )
    qa_case_execution._dispatch(
        "qa.run.complete",
        int(case["requirement_id"]),
        {
            "run_id": run_id,
            "verdict": verdict,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
        actor=actor,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "run_id": run_id,
        "artifact_id": int(artifact["qa_artifact_id"]),
        "executor_id": "worktree_run",
        "verdict": verdict,
        "case_outcome": "passed" if verdict == "pass" else "failed",
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "output_capture": str(streamed.capture_path),
        "timed_out": streamed.timed_out,
        "timeout_summary": timeout_summary,
        "verification_tree": tree.as_payload() if tree else None,
    }


__all__ = ["execute_worktree_case"]
