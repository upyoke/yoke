"""Client-local execution for materialized Command and Browser plan cases."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef

from yoke_core.domain import qa_case_command_stream
from yoke_core.domain import qa_constants
from yoke_core.domain import qa_start_bound_authority
from yoke_core.domain import test_gate_timeout
from yoke_core.domain import verification_tree_binding

#: Surface name carried by this executor's tree-binding refusal.
_TREE_BINDING_SURFACE = "qa case run"


class QaCaseExecutionError(RuntimeError):
    """A case contract is invalid or its executor cannot be run locally."""


def _dispatch(
    function_id: str,
    requirement_id: int,
    payload: dict,
    *,
    actor: Optional[ActorContext] = None,
) -> dict:
    from yoke_core.domain.qa_composed_dispatch import (
        call_qa_function,
    )

    response = call_qa_function(
        function_id=function_id,
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(requirement_id),
        ),
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise QaCaseExecutionError(f"{function_id} failed ({code}): {message}")
    return response.result or {}


def fetch_case_execution_context(
    requirement_id: int,
    *,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Authorize and fetch one immutable case before local side effects."""
    result = _dispatch(
        "qa.case_execution.begin",
        requirement_id,
        {},
        actor=actor,
    )
    case = result.get("case")
    if not isinstance(case, dict):
        raise QaCaseExecutionError("qa.case_execution.begin returned no case contract")
    return case


def _execution_checkout(case: dict) -> Path:
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
        worktree_path_for_branch,
    )

    project_id = int(case["project_id"])
    branch = str(case.get("lane_branch") or "").strip()
    if branch and branch != "null":
        worktree = worktree_path_for_branch(project_id, branch)
        if worktree is not None and worktree.is_dir():
            return worktree
    checkout = checkout_for_project_id(project_id)
    if checkout is None or not checkout.is_dir():
        raise QaCaseExecutionError(
            f"no local checkout is mapped for project {case['project']!r}"
        )
    return checkout


def _command_result(
    case: dict,
    *,
    base_url: str = "",
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict:
    config = case["method_config"]
    command = str(config.get("command") or "").strip()
    if not command:
        raise QaCaseExecutionError("Command case requires method_config.command")
    configured = config.get("timeout_seconds", 1200)
    timeout = int(timeout_seconds if timeout_seconds is not None else configured)
    if timeout < 1 or timeout > qa_constants.MAX_CASE_COMMAND_TIMEOUT_SECONDS:
        raise QaCaseExecutionError(
            "Command case timeout_seconds must be between 1 and "
            f"{qa_constants.MAX_CASE_COMMAND_TIMEOUT_SECONDS}"
        )
    checkout = (
        Path(checkout_path).resolve()
        if checkout_path is not None
        else _execution_checkout(case)
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
    requirement_id = int(case["requirement_id"])
    # Every recording leg carries the authority the run bound at its start,
    # so an hour-long gate still records after a mid-run claim reclaim.
    authority = qa_start_bound_authority.payload_authority(case)

    def record_leg(function_id: str, payload: dict) -> dict:
        return _dispatch(
            function_id, requirement_id, {**authority, **payload}, actor=actor
        )

    run = record_leg(
        "qa.run.add",
        {
            "executor_type": "worktree_run",
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    run_id = int(run["qa_run_id"])
    from yoke_core.domain.qa_artifact_handle import local_handle
    from yoke_core.domain.qa_artifacts import artifact_file_path, case_artifact_subject

    output_path = artifact_file_path(
        str(case["project"]),
        case_artifact_subject(case),
        run_id,
        "command-output.txt",
    )
    output_path.write_text(output, encoding="utf-8")
    artifact = record_leg(
        "qa.artifact.add",
        {
            "run_id": run_id,
            "artifact_type": "command_output",
            "content_type": "text/plain",
            "artifact_handle": local_handle(str(output_path.resolve()), "text/plain"),
            "metadata": json.dumps(
                {
                    "case_key": case["case_key"],
                    "exit_code": exit_code,
                    "timed_out": streamed.timed_out,
                },
                sort_keys=True,
            ),
        },
    )
    record_leg(
        "qa.run.complete",
        {
            "run_id": run_id,
            "verdict": verdict,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    return {
        "requirement_id": requirement_id,
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


def _browser_result(
    case: dict,
    *,
    base_url: str,
    expected_branch: Optional[str],
    expected_sha: Optional[str],
    actor: Optional[ActorContext] = None,
) -> dict:
    from yoke_core.domain.browser_qa import execute_scenario

    result = execute_scenario(
        item_id=int(case["item_id"]),
        project=str(case["project"]),
        base_url=base_url,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        requirement_id=int(case["requirement_id"]),
        actor=actor,
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "executor_id": "browser_substrate",
        **json.loads(result.to_json()),
    }


def execute_case_context(
    case: dict,
    *,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Execute a server-authorized immutable case context locally."""
    executor_id = str(case["executor_id"])
    if executor_id == "worktree_run":
        return _command_result(
            case,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            checkout_path=checkout_path,
            actor=actor,
        )
    if executor_id == "browser_substrate":
        return _browser_result(
            case,
            base_url=base_url,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
            actor=actor,
        )
    if executor_id == "host_control":
        from yoke_core.domain.machine_qa_case_execution import (
            execute_materialized_machine_case,
        )

        return execute_materialized_machine_case(case, actor=actor)
    raise QaCaseExecutionError(
        f"executor {executor_id!r} is not supported by shared case execution"
    )


def execute_case(
    requirement_id: int,
    *,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Authorize, snapshot, and execute one registered materialized case."""
    case = fetch_case_execution_context(requirement_id, actor=actor)
    return execute_case_context(
        case,
        base_url=base_url,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        timeout_seconds=timeout_seconds,
        checkout_path=checkout_path,
        actor=actor,
    )


__all__ = [
    "QaCaseExecutionError",
    "execute_case",
    "execute_case_context",
    "fetch_case_execution_context",
]
