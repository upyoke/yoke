"""Dispatch a materialized plan case to the executor its method names.

The per-executor implementations live beside this module —
:mod:`yoke_core.domain.qa_case_worktree_run` (local command),
:mod:`yoke_core.domain.qa_case_ci_run` (the project's CI workflow),
:mod:`yoke_core.domain.browser_qa`, and
:mod:`yoke_core.domain.machine_qa_case_execution`. What stays here is
what they share: the authorized case context, the qa.* function-call
boundary, and the checkout an executor runs against.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef

from yoke_core.domain import qa_start_bound_authority


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


def recording_leg(
    case: dict,
    *,
    actor: Optional[ActorContext] = None,
) -> Callable[[str, dict], dict]:
    """Return the dispatcher an executor's run/artifact legs share.

    Binds the requirement the run belongs to, the calling actor, and the
    authority the run pinned at ``qa.case_execution.begin``. That last
    part is what lets a gate measured in tens of minutes record the
    verdict it earned after the stale-session sweep reclaimed the live
    claim mid-run.
    """
    requirement_id = int(case["requirement_id"])
    authority = qa_start_bound_authority.payload_authority(case)

    def dispatch_leg(function_id: str, payload: dict) -> dict:
        return _dispatch(
            function_id, requirement_id, {**authority, **payload}, actor=actor
        )

    return dispatch_leg


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
    allow_tree_mismatch: bool = False,
    actor: Optional[ActorContext] = None,
) -> dict:
    """Execute a server-authorized immutable case context locally."""
    executor_id = str(case["executor_id"])
    if executor_id == "worktree_run":
        from yoke_core.domain.qa_case_worktree_run import execute_worktree_case

        return execute_worktree_case(
            case, base_url=base_url, timeout_seconds=timeout_seconds,
            checkout_path=checkout_path,
            allow_tree_mismatch=allow_tree_mismatch, actor=actor,
        )
    if executor_id == "ci_run":
        from yoke_core.domain.qa_case_ci_run import execute_ci_case

        return execute_ci_case(
            case, timeout_seconds=timeout_seconds,
            checkout_path=checkout_path,
            allow_tree_mismatch=allow_tree_mismatch, actor=actor,
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
    allow_tree_mismatch: bool = False,
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
        allow_tree_mismatch=allow_tree_mismatch,
        actor=actor,
    )


__all__ = [
    "QaCaseExecutionError",
    "execute_case",
    "execute_case_context",
    "fetch_case_execution_context",
]
