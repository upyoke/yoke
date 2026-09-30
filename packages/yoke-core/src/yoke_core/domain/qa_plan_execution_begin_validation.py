"""Validate a begun QA plan execution, and release it when it cannot run.

``qa.plan_execution.begin`` has already persisted an ACTIVE execution row by
the time its response is read. Every refusal that follows -- an invalid
roster, an unusable cursor, a base URL the immutable execution target does
not allow -- therefore refuses *after* durable state exists. Left behind,
that row is indistinguishable from a walk somebody is driving: it holds the
subject, and a deployment run's settlement waits on it until a holder aborts
it by hand.

So the validations live together, in one call, and the caller releases the
row on any of them. The refusal the caller raises then says both things --
why the plan cannot run, and that nothing was left holding the subject.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.domain.qa_project_execution_target import resolve_execution_base_url
from yoke_core.domain.machine_qa_case_machine import resolve_plan_machine


@dataclass(frozen=True)
class BegunPlanExecution:
    """One begun execution whose response is usable as issued."""

    requirements: list[dict[str, Any]]
    cursor: int
    recorded_results: list[dict[str, Any]]
    selected_machine: Optional[str]
    resolved_base_url: str


def begun_execution_id(execution: Mapping[str, Any]) -> str:
    """Return the execution id the begin response names, refusing none.

    This is read before the other validations because it is the handle that
    releases them: a response naming no execution has nothing to release,
    and refusing here keeps every later refusal recoverable.
    """
    execution_id = str(execution.get("execution_id") or "")
    if not execution_id:
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned no execution id, so nothing "
            "names the execution it started and nothing here can release it. "
            "Re-run the plan; a repeat is a control-plane defect to report "
            "rather than a client-side retry"
        )
    return execution_id


def validate_begun_execution(
    execution: Mapping[str, Any],
    *,
    machine: Optional[str],
    base_url: str,
) -> BegunPlanExecution:
    """Refuse a begun execution this client cannot run as issued."""
    requirements = execution.get("requirements")
    if not isinstance(requirements, list) or any(
        not isinstance(row, dict) for row in requirements
    ):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned an invalid requirement roster"
        )
    try:
        selected_machine = resolve_plan_machine(requirements, machine)
    except ValueError as exc:
        raise QaPlanExecutionError(str(exc)) from exc
    cursor = int(execution.get("cursor_ordinal") or 0)
    if cursor < 0 or cursor > len(requirements):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned an invalid durable cursor"
        )
    stored_results = execution.get("results") or []
    if not isinstance(stored_results, list):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned invalid recorded results"
        )
    execution_target = execution.get("execution_target")
    if not isinstance(execution_target, dict):
        raise QaPlanExecutionError("qa.plan_execution.begin returned no target")
    try:
        resolved_base_url = resolve_execution_base_url(
            execution_target,
            requirements,
            base_url,
        )
    except ValueError as exc:
        raise QaPlanExecutionError(str(exc)) from exc
    return BegunPlanExecution(
        requirements=list(requirements),
        cursor=cursor,
        recorded_results=[
            dict(entry["result"])
            for entry in stored_results
            if isinstance(entry, dict) and isinstance(entry.get("result"), dict)
        ],
        selected_machine=selected_machine,
        resolved_base_url=resolved_base_url,
    )


def release_unusable_execution(
    call_plan_function,
    *,
    target: Any,
    execution_id: str,
    subject_flag: str,
    actor: Any,
    error: QaPlanExecutionError,
) -> QaPlanExecutionError:
    """Abort the execution this refusal cannot use, then return the refusal.

    The abort is reported in the refusal either way: a released row needs no
    follow-up, and one that could not be released needs the named manual
    abort before this subject can be walked again. ``subject_flag`` is the
    ``--item``/``--deployment-run-id`` selector the manual abort needs, so
    the recovery is an invocation rather than a command that would refuse
    for want of a subject.
    """
    from yoke_core.domain.qa_plan_execution_abort_reason import (
        REASON_DETAIL_SEPARATOR,
        UNUSABLE_BEGIN_REASON,
    )

    detail = " ".join(str(error).split())
    try:
        call_plan_function(
            function_id="qa.plan_execution.abort",
            target=target,
            payload={
                "execution_id": execution_id,
                "reason": f"{UNUSABLE_BEGIN_REASON}{REASON_DETAIL_SEPARATOR}{detail}",
            },
            actor=actor,
        )
    except QaPlanExecutionError as abort_error:
        return QaPlanExecutionError(
            f"{detail}. Execution {execution_id} was started before this "
            f"refusal and could not be released: {abort_error}. It still holds "
            "this subject, so release it with `yoke qa plan abort "
            f"{subject_flag} --execution-id {execution_id} --reason "
            '"begin response unusable"` before re-running the plan'
        )
    return QaPlanExecutionError(
        f"{detail}. Execution {execution_id} was started before this refusal "
        "and has been released, so nothing holds this subject; correct the "
        "plan or the arguments and re-run"
    )


__all__ = [
    "BegunPlanExecution",
    "begun_execution_id",
    "release_unusable_execution",
    "validate_begun_execution",
]
