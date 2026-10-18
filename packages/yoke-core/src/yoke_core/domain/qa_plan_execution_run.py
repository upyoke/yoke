"""Stage-ordered, client-local execution of materialized QA plan cases."""

from __future__ import annotations


from yoke_core.domain.qa_plan_execution_abort_reason import (
    case_failed_reason,
    member_removed,
)
from yoke_core.domain.qa_plan_execution_result_state import (
    QaPlanExecutionError,
    aggregate_state as _aggregate_state,
    case_failed,
    plan_order as _plan_order,
)
from yoke_core.domain.qa_plan_execution_continuation import continuation_abort_reason
from yoke_core.domain.qa_plan_host_free_cases import (
    run_host_free_cases_while_waiting,
    waiting_recovery,
)


def execute_begun_plan(
    *,
    execution,
    begun,
    target,
    resolved_actor,
    transition_id,
    expected_branch,
    expected_sha,
    timeout_seconds,
    checkout_path,
    allow_tree_mismatch,
    call_plan_function,
):
    _call_plan_function = call_plan_function
    execution_id = str(execution["execution_id"])
    requirements = begun.requirements
    cursor = begun.cursor
    resolved_base_url = begun.resolved_base_url
    machine_options = (
        {"machine": begun.selected_machine} if begun.selected_machine else {}
    )
    from yoke_core.domain.qa_plan_execution_checkin import (
        communication_unknown,
        paused_result,
    )

    deliveries = []
    recorded_results = begun.recorded_results
    results = [dict(result) for result in recorded_results]
    state = "passed"
    failed_cases: list[int] = []
    raised = False
    for recorded in recorded_results:
        state = _aggregate_state(state, recorded)
        if case_failed(recorded):
            failed_cases.append(int(recorded["requirement_id"]))
    from yoke_core.domain.qa_case_execution import execute_case_context

    def _execute_local(requirement):
        return execute_case_context(
            requirement,
            base_url=resolved_base_url,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
            timeout_seconds=timeout_seconds,
            checkout_path=checkout_path,
            allow_tree_mismatch=allow_tree_mismatch,
            actor=resolved_actor,
        )

    def _check_in():
        checked = _call_plan_function(
            function_id="qa.plan_execution.heartbeat",
            target=target,
            payload={"execution_id": execution_id},
            actor=resolved_actor,
        )
        if checked.get("delivery"):
            deliveries.append(checked["delivery"])

    def _record(ordinal, normalized):
        _call_plan_function(
            function_id="qa.plan_execution.advance",
            target=target,
            payload={
                "execution_id": execution_id,
                "ordinal": ordinal,
                "requirement_id": int(normalized["requirement_id"]),
                "result": normalized,
            },
            actor=resolved_actor,
        )

    # Host-free cases recorded ahead while an earlier walk queued for a host.
    done_ordinals = set(begun.recorded_ordinals)
    for ordinal in range(cursor, len(requirements)):
        if ordinal in done_ordinals:
            continue
        requirement = requirements[ordinal]
        requirement_id = int(requirement["requirement_id"])
        order = _plan_order(requirement)
        phase = "checkin"
        try:
            _check_in()
            phase = "case"
            if requirement.get("runner_id") == "host_control":
                from yoke_core.domain.machine_qa_plan_case_execution import (
                    execute_plan_machine_case,
                )

                result = execute_plan_machine_case(
                    requirement,
                    execution_id=execution_id,
                    ordinal=ordinal,
                    actor=resolved_actor,
                    **machine_options,
                )
                advance_result = False
            elif requirement.get("runner_id") == "agent_mission":
                from yoke_core.domain.machine_qa_plan_case_execution import (
                    execute_plan_agent_mission_case,
                )

                result = execute_plan_agent_mission_case(
                    requirement,
                    execution_id=execution_id,
                    ordinal=ordinal,
                    actor=resolved_actor,
                    **machine_options,
                )
                advance_result = False
            else:
                result = _execute_local(requirement)
                advance_result = True
            if int(result.get("requirement_id") or 0) != requirement_id:
                raise QaPlanExecutionError(
                    f"case runner returned the wrong requirement for {requirement_id}"
                )
            normalized = {**order, **result}
            phase = "recording"
            if advance_result:
                _record(ordinal, normalized)
        except BaseException as exc:
            if unknown := communication_unknown(exc):
                return paused_result(
                    error=unknown,
                    call=_call_plan_function,
                    execution=execution,
                    target=target,
                    actor=resolved_actor,
                    phase=phase,
                    cursor=ordinal,
                    results=results,
                )
            if phase == "checkin" and isinstance(exc, QaPlanExecutionError):
                return {
                    "execution_id": execution_id,
                    "state": "blocked_on_precondition",
                    "reason": "qa_checkin_refused",
                    "results": results,
                    "recovery": str(exc),
                }
            try:
                closed = _call_plan_function(
                    function_id="qa.plan_execution.abort",
                    target=target,
                    payload={
                        "execution_id": execution_id,
                        "reason": continuation_abort_reason(execution, exc),
                    },
                    actor=resolved_actor,
                )
            except QaPlanExecutionError as abort_exc:
                raise QaPlanExecutionError(
                    f"QA case failed and execution {execution_id} could not close: "
                    f"{abort_exc}. Abort that execution, then retry the corrected plan"
                ) from abort_exc
            if not isinstance(exc, Exception):
                raise
            raised = True
            if member_removed(closed):
                # The run removed this member mid-case; the case's error is
                # that interruption, not a failure of its host.
                results.append(
                    {
                        "requirement_id": requirement_id,
                        **order,
                        "case_outcome": "removed",
                    }
                )
                state = "removed"
                break
            results.append(
                {
                    "requirement_id": requirement_id,
                    **order,
                    "case_outcome": "error",
                    "error": str(exc),
                }
            )
            state = "error"
            break
        results.append(normalized)
        state = _aggregate_state(state, normalized)
        # A failed case's inheriting followers still pass through here: the
        # server records each one blocked without touching the machine, and
        # the next named-baseline or as-is chain runs from its own reset.
        if case_failed(normalized):
            failed_cases.append(requirement_id)
        if _aggregate_state("passed", normalized) == "waiting":
            if begun.host_free_cases_ahead:
                # Queued for a host: run the host-free automatic cases first,
                # then park. Their failures are recorded, not a reason to
                # leave the line.
                ran, skipped = run_host_free_cases_while_waiting(
                    requirements=requirements,
                    after_ordinal=ordinal,
                    done_ordinals=done_ordinals,
                    execute_case=_execute_local,
                    record_result=_record,
                    check_in=_check_in,
                )
                failed_cases.extend(
                    int(row["requirement_id"]) for row in ran if case_failed(row)
                )
                results[-1:-1] = ran
                normalized["recovery"] = waiting_recovery(
                    normalized.get("recovery"), ran, skipped
                )
            state = "waiting"
            break

    if failed_cases and not raised and state != "waiting":
        _call_plan_function(
            function_id="qa.plan_execution.abort",
            target=target,
            payload={
                "execution_id": execution_id,
                "reason": case_failed_reason(failed_cases),
            },
            actor=resolved_actor,
        )
        if state not in {"failed", "error"}:
            state = "failed"

    review_bundle = None
    if len(results) == len(requirements) and state not in {
        "failed",
        "error",
        "waiting",
        "removed",
    }:
        try:
            review = _call_plan_function(
                function_id="qa.plan_review.begin",
                target=target,
                payload={"execution_id": execution_id},
                actor=resolved_actor,
            )
            review_bundle = review.get("review_bundle")
            if review_bundle is not None:
                state = "awaiting_agent_review"
            else:
                _call_plan_function(
                    function_id="qa.plan_execution.complete",
                    target=target,
                    payload={"execution_id": execution_id},
                    actor=resolved_actor,
                )
        except QaPlanExecutionError as exc:
            if unknown := communication_unknown(exc):
                return paused_result(
                    error=unknown,
                    call=_call_plan_function,
                    execution=execution,
                    target=target,
                    actor=resolved_actor,
                    phase="review",
                    cursor=len(requirements),
                    results=results,
                )
            raise

    return {
        "execution_id": execution_id,
        "checkin_delivery": deliveries,
        "remaining_requirement_count": execution.get("remaining_requirement_count"),
        "item_id": (
            int(execution["item_id"]) if execution.get("item_id") is not None else None
        ),
        "deployment_run_id": execution.get("deployment_run_id"),
        "standalone_plan_id": execution.get("standalone_plan_id"),
        "deployment_stage": execution.get("deployment_stage"),
        "deployment_member_item_id": execution.get("deployment_member_item_id"),
        "transition_id": transition_id,
        "state": state,
        # A completed capture awaiting its independent review carries no QA
        # verdict yet; the reviewer's submitted batch is the verdict.
        "review_status": "pending" if review_bundle is not None else None,
        "requirement_count": len(requirements),
        "executed_count": len(results),
        "results": results,
        "review_bundle": review_bundle,
        "recovery": _recovery(state, failed_cases, results, raised=raised),
    }


def _recovery(
    state: str, failed_cases: list[int], results: list[dict], *, raised: bool
) -> str | None:
    if state == "waiting" and results:
        return results[-1].get("recovery")
    if state == "removed":
        return (
            "The deployment run removed this item while its QA was running, so "
            "the execution was cancelled with nothing recorded as passed; no "
            "host needs repair. The item owes its QA in its next release."
        )
    if state not in {"failed", "error"}:
        return None
    rerun = (
        "Correct the case or plan and rerun yoke qa plan run; "
        "no manual abort is needed."
    )
    if raised or not failed_cases:
        return f"QA execution closed after a case raised while running. {rerun}"
    named = ", ".join(str(requirement_id) for requirement_id in failed_cases)
    return (
        f"QA execution ran every independent chain and closed after failed "
        f"case requirements {named}. Cases chained behind a failed case are "
        f"recorded blocked (inherited_predecessor_not_passed) and did not run. "
        f"{rerun}"
    )
