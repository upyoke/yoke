"""Stage-ordered, client-local execution of materialized QA plan cases."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_execution_result_state import (
    BASELINE_GROUP_RESULTS as _BASELINE_GROUP_RESULTS,
    QaPlanExecutionError,
    aggregate_state as _aggregate_state,
    plan_order as _plan_order,
    public_plan_result as _public_plan_result,
    remember_baseline_group_results as _remember_baseline_group_results,
    validated_baseline_group_results as _validated_baseline_group_results,
)
from yoke_core.domain.qa_plan_execution_continuation import continuation_abort_reason


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
    recorded_results = begun.recorded_results
    baseline_group_results: dict[int, dict[str, Any]] = {}
    for recorded in recorded_results:
        cached = recorded.get(_BASELINE_GROUP_RESULTS)
        if cached is not None:
            _remember_baseline_group_results(baseline_group_results, cached)
    results = [_public_plan_result(result) for result in recorded_results]
    state = "passed"
    for recorded in recorded_results:
        state = _aggregate_state(state, recorded)
    from yoke_core.domain.qa_case_execution import execute_case_context

    for ordinal in range(cursor, len(requirements)):
        requirement = requirements[ordinal]
        requirement_id = int(requirement["requirement_id"])
        order = _plan_order(requirement)
        try:
            durable_group: list[dict[str, Any]] | None = None
            _call_plan_function(
                function_id="qa.plan_execution.heartbeat",
                target=target,
                payload={"execution_id": execution_id},
                actor=resolved_actor,
            )
            if requirement.get("runner_id") == "host_control":
                standalone_id = requirement.get("standalone_execution_id")
                if (
                    requirement.get("host_baseline")
                    and not standalone_id
                    and execution.get("remaining_requirement_count") is None
                ):
                    if requirement_id not in baseline_group_results:
                        from yoke_core.domain.machine_qa_case_execution import (
                            execute_materialized_machine_baseline_group,
                        )

                        group = execute_materialized_machine_baseline_group(
                            requirement,
                            actor=resolved_actor,
                            **machine_options,
                        )
                        discovered, baseline_ok = _validated_baseline_group_results(
                            group,
                            anchor=requirement,
                            requirements=requirements,
                        )
                        if baseline_ok is not None:
                            baseline_group_results.update(discovered)
                            durable_group = [
                                discovered[int(case["requirement_id"])]
                                for case in requirements
                                if int(case["requirement_id"]) in discovered
                            ]
                        result = discovered[requirement_id]
                    else:
                        result = baseline_group_results[requirement_id]
                        baseline_ok = True
                    advance_result = baseline_ok is not None
                else:
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
                result = execute_case_context(
                    requirement,
                    base_url=resolved_base_url,
                    expected_branch=expected_branch,
                    expected_sha=expected_sha,
                    timeout_seconds=timeout_seconds,
                    checkout_path=checkout_path,
                    allow_tree_mismatch=allow_tree_mismatch,
                    actor=resolved_actor,
                )
                advance_result = True
            if int(result.get("requirement_id") or 0) != requirement_id:
                raise QaPlanExecutionError(
                    f"case runner returned the wrong requirement for {requirement_id}"
                )
            normalized = {**order, **result}
            durable_result = (
                {
                    **normalized,
                    _BASELINE_GROUP_RESULTS: durable_group,
                }
                if requirement.get("host_baseline") and durable_group is not None
                else normalized
            )
            if advance_result:
                _call_plan_function(
                    function_id="qa.plan_execution.advance",
                    target=target,
                    payload={
                        "execution_id": execution_id,
                        "ordinal": ordinal,
                        "requirement_id": requirement_id,
                        "result": durable_result,
                    },
                    actor=resolved_actor,
                )
        except BaseException as exc:
            failed = {
                "requirement_id": requirement_id,
                **order,
                "case_outcome": "error",
                "error": str(exc),
            }
            results.append(failed)
            try:
                _call_plan_function(
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
            state = "error"
            break
        results.append(normalized)
        state = _aggregate_state(state, normalized)
        if (
            state in {"failed", "error"}
            or normalized.get("execution_status") == "capture_failed"
        ):
            _call_plan_function(
                function_id="qa.plan_execution.abort",
                target=target,
                payload={
                    "execution_id": execution_id,
                    "reason": f"qa-plan-case-{requirement_id}-failed",
                },
                actor=resolved_actor,
            )
            if state not in {"failed", "error"}:
                state = "failed"
            break
        if state in {"error", "waiting"}:
            break

    review_bundle = None
    if len(results) == len(requirements) and state not in {
        "failed",
        "error",
        "waiting",
    }:
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
    return {
        "execution_id": execution_id,
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
        "recovery": (
            "QA execution closed after a failed capture or runner result. "
            "Correct the case or plan and rerun yoke qa plan run; no manual abort is needed."
            if state in {"failed", "error"}
            else None
        ),
    }
