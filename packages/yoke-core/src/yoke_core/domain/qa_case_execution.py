"""Client-local execution for materialized Command and Browser plan cases."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import TargetRef


class QaCaseExecutionError(RuntimeError):
    """A case contract is invalid or its executor cannot be run locally."""


def _dispatch(
    function_id: str, requirement_id: int, payload: dict,
) -> dict:
    from yoke_core.api.service_client_structured_api_adapter import (
        call_dispatcher,
    )

    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=int(requirement_id),
        ),
        payload=payload,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise QaCaseExecutionError(
            f"{function_id} failed ({code}): {message}"
        )
    return response.result or {}


def fetch_case_execution_context(requirement_id: int) -> dict:
    """Fetch one immutable case snapshot through the registered read."""
    result = _dispatch("qa.case_execution.get", requirement_id, {})
    case = result.get("case")
    if not isinstance(case, dict):
        raise QaCaseExecutionError(
            "qa.case_execution.get returned no case contract"
        )
    return case


def _execution_checkout(case: dict) -> Path:
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
        worktree_path_for_branch,
    )

    project_id = int(case["project_id"])
    branch = str(case.get("worktree") or "").strip()
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


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _command_result(
    case: dict,
    *,
    base_url: str = "",
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
) -> dict:
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
        else _execution_checkout(case)
    )
    if not checkout.is_dir():
        raise QaCaseExecutionError(
            f"command execution checkout does not exist: {checkout}"
        )
    command_env = dict(os.environ)
    if config.get("requires_base_url"):
        if not base_url:
            raise QaCaseExecutionError(
                "this Command case requires --base-url"
            )
        command_env["BASE_URL"] = base_url
    started = time.monotonic()
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable="/bin/sh",
            cwd=str(checkout),
            env=command_env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        exit_code = int(completed.returncode)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = _text(exc.stdout)
        stderr = _text(exc.stderr)
        stderr += f"\ncommand timed out after {timeout} seconds\n"
    duration_ms = int((time.monotonic() - started) * 1000)
    verdict = "pass" if exit_code == 0 else "fail"
    output = (
        f"$ {command}\n\n[stdout]\n{stdout}\n\n"
        f"[stderr]\n{stderr}\n\n[exit_code]\n{exit_code}\n"
    )
    raw_result = json.dumps({
        "command": command,
        "cwd": str(checkout),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "output_tail": output[-16000:],
    }, sort_keys=True)
    run = _dispatch(
        "qa.run.add",
        int(case["requirement_id"]),
        {
            "executor_type": "worktree_run",
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
    )
    run_id = int(run["qa_run_id"])
    from yoke_core.domain.qa_artifact_handle import local_handle
    from yoke_core.domain.qa_artifacts import artifact_file_path

    output_path = artifact_file_path(
        str(case["project"]),
        int(case["item_id"]),
        run_id,
        "command-output.txt",
    )
    output_path.write_text(output, encoding="utf-8")
    artifact = _dispatch(
        "qa.artifact.add",
        int(case["requirement_id"]),
        {
            "run_id": run_id,
            "artifact_type": "command_output",
            "content_type": "text/plain",
            "artifact_handle": local_handle(
                str(output_path.resolve()), "text/plain",
            ),
            "metadata": json.dumps({
                "case_key": case["case_key"],
                "exit_code": exit_code,
                "timed_out": timed_out,
            }, sort_keys=True),
        },
    )
    _dispatch(
        "qa.run.complete",
        int(case["requirement_id"]),
        {
            "run_id": run_id,
            "verdict": verdict,
            "raw_result": raw_result,
            "duration_ms": duration_ms,
        },
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
    }


def _browser_result(
    case: dict,
    *,
    base_url: str,
    expected_branch: Optional[str],
    expected_sha: Optional[str],
) -> dict:
    from yoke_core.domain.browser_qa import execute_scenario

    result = execute_scenario(
        item_id=int(case["item_id"]),
        project=str(case["project"]),
        base_url=base_url,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        requirement_id=int(case["requirement_id"]),
    )
    return {
        "requirement_id": int(case["requirement_id"]),
        "executor_id": "browser_substrate",
        **json.loads(result.to_json()),
    }


def execute_case(
    requirement_id: int,
    *,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
) -> dict:
    """Execute one materialized case through its registered executor."""
    case = fetch_case_execution_context(requirement_id)
    executor_id = str(case["executor_id"])
    if executor_id == "worktree_run":
        return _command_result(
            case,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            checkout_path=checkout_path,
        )
    if executor_id == "browser_substrate":
        return _browser_result(
            case,
            base_url=base_url,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
        )
    if executor_id == "host_control":
        from yoke_core.domain.machine_qa_case_execution import (
            execute_materialized_machine_case,
        )

        return execute_materialized_machine_case(case)
    raise QaCaseExecutionError(
        f"executor {executor_id!r} is not supported by shared case execution"
    )


__all__ = [
    "QaCaseExecutionError",
    "execute_case",
    "fetch_case_execution_context",
]
