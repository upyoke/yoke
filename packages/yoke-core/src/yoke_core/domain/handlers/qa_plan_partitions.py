"""Registered read of the partition roster and frozen source lane."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from yoke_contracts.api.function_call import FunctionCallRequest, FunctionError, HandlerOutcome
from yoke_core.domain.qa_plan_partition_custody import PartitionScope


class PlanPartitionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_id: str | None = Field(default=None, min_length=1)
    plan: str | None = Field(default=None, min_length=1)
    source_revision: str | None = None
    checkout_path: str | None = None
    expected_branch: str | None = None
    deployment_stage: str | None = Field(default=None, min_length=1)
    deployment_member: str | None = Field(default=None, min_length=1)
    deployment_run_id: str | None = Field(default=None, min_length=1)


class PlanPartitionsResponse(BaseModel):
    partitions: list[dict[str, Any]]
    lane: dict[str, Any] | None = None


def handle_plan_partitions(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.qa_item_deployment_request import resolve_item_deployment_request
    from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError

    try:
        with connect() as conn:
            request = resolve_item_deployment_request(conn, request)
            parsed = PlanPartitionsRequest.model_validate(request.payload)
            return HandlerOutcome(
                primary_success=True,
                result_payload=_partitions(conn, request, parsed),
            )
    except (LookupError, ValueError, QaPlanExecutionError) as exc:
        return HandlerOutcome(
            primary_success=False,
            error=FunctionError(
                code=getattr(exc, "code", "qa_partitions_failed"),
                message=str(exc),
                jsonpath="$.payload",
            ),
        )


def _partitions(conn, request, parsed):
    from yoke_core.domain.qa_case_source_lane import resolve_source_lane
    from yoke_core.domain.qa_item_deployment_request import execution_member_id
    from yoke_core.domain.qa_plan_empty_roster import QaPlanRosterDischarged
    from yoke_core.domain.qa_plan_execution_store import build_execution_roster
    from yoke_core.domain.qa_plan_partitions import scoped_partition_views

    if request.target.kind == "global":
        return {"partitions": _standalone(conn, request, parsed)}
    item_id = request.target.item_id
    run_id = request.target.deployment_run_id
    member = execution_member_id(conn, parsed.deployment_member)
    stage = parsed.deployment_stage
    if item_id is not None and (not parsed.transition_id or stage or parsed.plan):
        raise ValueError("Use --item ITEM --transition TRANSITION for attached item plans.")
    if run_id is not None and (not stage or parsed.transition_id):
        raise ValueError("Use --deployment-run-id RUN --stage STAGE for release partitions.")
    lane = None
    digest = None
    if item_id is not None:
        lane = resolve_source_lane(
            conn,
            item_id=item_id,
            session_id=request.actor.session_id,
            expected_branch=parsed.expected_branch,
            checkout_path=parsed.checkout_path,
        )
    if run_id is not None:
        digest, member = _deployment_target(conn, run_id, stage, member, parsed.plan)
    scope = PartitionScope(item_id, parsed.transition_id, run_id, stage, member)
    try:
        roster = build_execution_roster(
            conn,
            item_id=item_id,
            transition_id=parsed.transition_id,
            deployment_run_id=run_id,
            deployment_stage=stage,
            deployment_member_item_id=member,
            execution_target_digest=digest,
            plan=parsed.plan,
            checkout_path=parsed.checkout_path,
            expected_branch=parsed.expected_branch,
            session_id=request.actor.session_id,
        )
    except QaPlanRosterDischarged:
        roster = []
    views = scoped_partition_views(conn, scope, roster)
    partitions = [view.as_dict() for view in views]
    if run_id is not None and roster:
        from yoke_core.domain.qa_plan_execution_store import marker

        manual = {
            int(row[0]) for row in conn.execute(
                f"SELECT id FROM qa_requirements WHERE id=ANY({marker(conn)}) AND wake_path='manual'",
                ([entry["requirement_id"] for entry in roster],),
            ).fetchall()
        }
        for partition in partitions:
            if any(case["requirement_id"] in manual for case in partition["cases"]):
                partition["wake_path"] = "manual"
    return {"partitions": partitions, "lane": lane or None}


def _standalone(conn, request, parsed):
    from yoke_core.domain.qa_plan_retire import resolve_plan
    from yoke_core.domain.qa_standalone_partitions import standalone_partition_views

    if not parsed.plan or parsed.transition_id or parsed.deployment_stage:
        raise ValueError("Use --plan PLAN --project PROJECT for standalone partitions.")
    plan = resolve_plan(conn, project=str(request.target.project_id), plan=parsed.plan)
    if plan["retired_at"] is not None:
        raise ValueError("standalone_plan_retired: select a live project plan.")
    return [
        view.as_dict()
        for view in standalone_partition_views(
            conn, int(plan["id"]), source_revision=parsed.source_revision
        )
    ]


def _deployment_target(conn, run_id, stage, member, plan):
    from yoke_core.domain.deployment_qa_execution_target import deployment_qa_execution_target
    from yoke_core.domain.deployment_qa_plan_group_writes import resolve_group_subject
    from yoke_core.domain.deployment_qa_stage_contract import deployment_qa_stage_subject
    from yoke_core.domain.qa_execution_environment_target import target_digest

    subject = (
        resolve_group_subject(conn, run_id, stage, plan, require_active=True, member=member)
        if plan else None
    )
    if subject is not None:
        member = None
    else:
        subject = deployment_qa_stage_subject(
            conn, run_id=run_id, stage_name=stage, member_item_id=member,
        )
    return target_digest(deployment_qa_execution_target(conn, subject)), member
