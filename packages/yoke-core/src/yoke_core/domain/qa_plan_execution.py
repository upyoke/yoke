"""Stage-ordered, client-local execution of materialized QA plan cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain import db_backend
from yoke_core.domain.qa_plan_execution_result_state import (
    BASELINE_GROUP_RESULTS as _BASELINE_GROUP_RESULTS,
)
from yoke_core.domain.qa_plan_execution_result_state import (
    QaPlanExecutionError,
    aggregate_state as _aggregate_state,
    plan_order as _plan_order,
    public_plan_result as _public_plan_result,
    remember_baseline_group_results as _remember_baseline_group_results,
    validated_baseline_group_results as _validated_baseline_group_results,
)
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target


def ordered_plan_requirements(
    conn: Any,
    *,
    item_id: int | None = None,
    transition_id: str | None = None,
    deployment_run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return server-authoritative execution order for one QA subject."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    if (item_id is None) == (deployment_run_id is None):
        raise QaPlanExecutionError("exactly one QA plan execution subject is required")
    if item_id is not None:
        where = f"item_id={marker} AND workflow_transition_id={marker}"
        params: tuple[Any, ...] = (int(item_id), str(transition_id))
        subject = f"item {item_id} transition {transition_id!r}"
    else:
        where = f"deployment_run_id={marker}"
        params = (str(deployment_run_id),)
        subject = f"deployment run {deployment_run_id!r}"
    cursor = conn.execute(
        "SELECT id AS requirement_id, plan_id, plan_case_key AS case_key, "
        "case_position, baseline_position, host_baseline, method_id, "
        "executor_id FROM qa_requirements "
        f"WHERE {where} "
        "AND plan_id IS NOT NULL AND waived_at IS NULL "
        "ORDER BY plan_id, case_position, baseline_position, id",
        params,
    )
    columns = [
        str(getattr(column, "name", None) or column[0]) for column in cursor.description
    ]
    requirements = [
        (
            {str(key): row[key] for key in row.keys()}
            if hasattr(row, "keys")
            else dict(zip(columns, row))
        )
        for row in cursor.fetchall()
    ]
    if not requirements:
        raise QaPlanExecutionError(f"{subject} has no materialized QA plan cases")
    for row in requirements:
        requirement_id = int(row["requirement_id"])
        if (
            row["case_position"] is None
            or row["baseline_position"] is None
            or not str(row["executor_id"] or "").strip()
        ):
            raise QaPlanExecutionError(
                f"materialized QA case {requirement_id} has an incomplete "
                "execution snapshot; apply the QA requirement snapshot migration"
            )
        row["requirement_id"] = requirement_id
        row["plan_id"] = int(row["plan_id"])
        row["case_position"] = int(row["case_position"])
        row["baseline_position"] = int(row["baseline_position"])
    return requirements


def _call_plan_function(
    *,
    function_id: str,
    target: TargetRef,
    payload: dict[str, Any],
    actor: ActorContext,
) -> dict[str, Any]:
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id=function_id,
        target=target,
        payload=payload,
        actor=actor,
    )
    if not response.success:
        code = response.error.code if response.error else "unknown"
        message = response.error.message if response.error else ""
        raise QaPlanExecutionError(f"{function_id} failed ({code}): {message}")
    return dict(response.result or {})


def _execution_actor(actor: Optional[ActorContext]) -> ActorContext:
    if actor is not None:
        return actor
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    return build_actor()


def execute_plan(
    *,
    item_ref: Optional[str] = None,
    transition_id: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    plan: Optional[str] = None,
    project: Optional[str] = None,
    base_url: str = "",
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    actor: Optional[ActorContext] = None,
) -> dict[str, Any]:
    """Resume and execute one server-authorized immutable ordered roster."""
    target, begin_payload = build_plan_execution_target(
        item_ref=item_ref,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        plan=plan,
        project=project,
    )
    resolved_actor = _execution_actor(actor)
    if deployment_run_id:
        _call_plan_function(
            function_id="qa.plan.materialize",
            target=target,
            payload={"plan": plan, "project": project},
            actor=resolved_actor,
        )
    execution = _call_plan_function(
        function_id="qa.plan_execution.begin",
        target=target,
        payload=begin_payload,
        actor=resolved_actor,
    )
    requirements = execution.get("requirements")
    if not isinstance(requirements, list) or any(
        not isinstance(row, dict) for row in requirements
    ):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned an invalid requirement roster"
        )
    execution_id = str(execution.get("execution_id") or "")
    cursor = int(execution.get("cursor_ordinal") or 0)
    if not execution_id or cursor < 0 or cursor > len(requirements):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned an invalid durable cursor"
        )
    stored_results = execution.get("results") or []
    if not isinstance(stored_results, list):
        raise QaPlanExecutionError(
            "qa.plan_execution.begin returned invalid recorded results"
        )
    recorded_results = [
        dict(entry["result"])
        for entry in stored_results
        if isinstance(entry, dict) and isinstance(entry.get("result"), dict)
    ]
    baseline_group_results: dict[int, dict[str, Any]] = {}
    for recorded in recorded_results:
        cached = recorded.get(_BASELINE_GROUP_RESULTS)
        if cached is not None:
            _remember_baseline_group_results(
                baseline_group_results,
                cached,
            )
    results = [_public_plan_result(result) for result in recorded_results]
    state = "passed"
    for recorded in recorded_results:
        state = _aggregate_state(state, recorded)
    from yoke_core.domain.qa_case_execution import (
        QaCaseExecutionError,
        execute_case_context,
    )

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
            if requirement.get("executor_id") == "host_control":
                if requirement.get("host_baseline"):
                    if requirement_id not in baseline_group_results:
                        from yoke_core.domain.machine_qa_case_execution import (
                            execute_materialized_machine_baseline_group,
                        )

                        group = execute_materialized_machine_baseline_group(
                            requirement,
                            actor=resolved_actor,
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
                    )
                    advance_result = False
            else:
                result = execute_case_context(
                    requirement,
                    base_url=base_url,
                    expected_branch=expected_branch,
                    expected_sha=expected_sha,
                    timeout_seconds=timeout_seconds,
                    checkout_path=checkout_path,
                    actor=resolved_actor,
                )
                advance_result = True
            if int(result.get("requirement_id") or 0) != requirement_id:
                raise QaPlanExecutionError(
                    f"case executor returned the wrong requirement for {requirement_id}"
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
        except (QaCaseExecutionError, RuntimeError, ValueError, OSError) as exc:
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
                        "reason": "case-execution-or-recording-error",
                    },
                    actor=resolved_actor,
                )
            except QaPlanExecutionError:
                pass
            state = "error"
            break
        results.append(normalized)
        state = _aggregate_state(state, normalized)
        if state in {"error", "waiting"}:
            break

    if len(results) == len(requirements) and state not in {"error", "waiting"}:
        _call_plan_function(
            function_id="qa.plan_execution.complete",
            target=target,
            payload={"execution_id": execution_id},
            actor=resolved_actor,
        )
    return {
        "execution_id": execution_id,
        "item_id": (
            int(execution["item_id"]) if execution.get("item_id") is not None else None
        ),
        "deployment_run_id": execution.get("deployment_run_id"),
        "transition_id": transition_id,
        "state": state,
        "requirement_count": len(requirements),
        "executed_count": len(results),
        "results": results,
    }


__all__ = [
    "QaPlanExecutionError",
    "execute_plan",
    "ordered_plan_requirements",
]
