"""Stage-ordered, client-local execution of materialized QA plan cases."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.qa_plan_execution_result_state import (
    QaPlanExecutionError,
    aggregate_state as _aggregate_state,  # noqa: F401 -- public test seam
)
from yoke_core.domain.qa_plan_execution_dispatch import (
    call_plan_function,
    execution_actor,
)
from yoke_core.domain.qa_plan_execution_begin_validation import (
    begun_execution_id,
    release_unusable_execution,
    validate_begun_execution,
)
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements

from yoke_core.domain.qa_member_plan_execution import execute_member_partitions

_call_plan_function = call_plan_function


@execute_member_partitions
def execute_plan(
    *,
    public_ref: Optional[str] = None,
    transition_id: Optional[str] = None,
    deployment_run_id: Optional[str] = None,
    deployment_stage: Optional[str] = None,
    deployment_member: Optional[str] = None,
    plan: Optional[str] = None,
    project: Optional[str] = None,
    base_url: str = "",
    machine: Optional[str] = None,
    expected_branch: Optional[str] = None,
    expected_sha: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    checkout_path: Optional[str | Path] = None,
    allow_tree_mismatch: bool = False,
    continue_mission: bool = False,
    replacements: Optional[list[dict[str, Any]]] = None,
    actor: Optional[ActorContext] = None,
) -> dict[str, Any]:
    """Resume and execute one server-authorized immutable ordered roster."""
    target, begin_payload = build_plan_execution_target(
        public_ref=public_ref,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member=deployment_member,
        plan=plan,
        project=project,
    )
    resolved_actor = execution_actor(actor)
    if target.kind == "global":
        begin_payload.update(
            source_revision=expected_sha,
            source_ref=expected_branch,
            checkout_path=str(checkout_path) if checkout_path else None,
        )
    if deployment_run_id:
        materialize_payload = {"plan": plan, "project": project}
        if deployment_stage:
            materialize_payload["deployment_stage"] = deployment_stage
        if deployment_member:
            materialize_payload["deployment_member"] = deployment_member
        if replacements:
            materialize_payload["replacements"] = replacements
        _call_plan_function(
            function_id="qa.plan.materialize",
            target=target,
            payload=materialize_payload,
            actor=resolved_actor,
        )
    for key, value in (("machine", machine), ("continue_mission", continue_mission)):
        if value:
            begin_payload[key] = value
    try:
        execution = _call_plan_function(
            function_id="qa.plan_execution.begin",
            target=target,
            payload=begin_payload,
            actor=resolved_actor,
        )
    except QaPlanExecutionError as exc:
        from yoke_core.domain.qa_plan_empty_roster import as_discharged_plan_result

        discharged = as_discharged_plan_result(exc)
        if discharged is None:
            raise
        print(f"yoke qa plan run: {discharged['message']}", file=sys.stderr)
        return discharged
    if (
        execution.get("state") == "completed"
        and execution.get("remaining_requirement_count") == 0
    ):
        from yoke_core.domain.qa_member_plan_execution import completed_member_result

        return completed_member_result(execution)
    execution_id = begun_execution_id(execution)
    try:
        begun = validate_begun_execution(execution, machine=machine, base_url=base_url)
        from yoke_core.domain.qa_standalone_command import preflight_standalone_runners

        preflight_standalone_runners(
            begun.requirements,
            checkout_path=checkout_path,
            expected_branch=expected_branch,
            expected_sha=expected_sha,
        )
    except QaPlanExecutionError as exc:
        raise release_unusable_execution(
            _call_plan_function,
            target=target,
            execution_id=execution_id,
            subject_flag=(
                f"--deployment-run-id {deployment_run_id}"
                if deployment_run_id
                else f"--item {public_ref}"
                if public_ref
                else f"--project {project}"
            ),
            actor=resolved_actor,
            error=exc,
        ) from exc
    from yoke_core.domain.qa_plan_execution_run import execute_begun_plan

    return execute_begun_plan(
        execution=execution,
        begun=begun,
        target=target,
        resolved_actor=resolved_actor,
        transition_id=transition_id,
        expected_branch=expected_branch,
        expected_sha=expected_sha,
        timeout_seconds=timeout_seconds,
        checkout_path=checkout_path,
        allow_tree_mismatch=allow_tree_mismatch,
        call_plan_function=_call_plan_function,
    )


__all__ = ["QaPlanExecutionError", "execute_plan", "ordered_plan_requirements"]
