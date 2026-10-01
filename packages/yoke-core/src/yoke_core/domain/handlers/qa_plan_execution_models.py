"""Typed payload and response models for ordered QA execution."""

from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from yoke_core.domain import qa_plan_execution_abort_reason as abort_reasons


class PlanExecutionBeginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transition_id: str | None = Field(default=None, min_length=1)
    plan: str | None = Field(default=None, min_length=1)
    source_revision: str | None = None
    source_ref: str | None = None
    checkout_path: str | None = None
    deployment_stage: str | None = Field(default=None, min_length=1)
    deployment_member: str | None = Field(default=None, min_length=1)
    machine: str | None = Field(default=None, min_length=1)
    #: Resume a stale-settled mission on its existing roster and host.
    continue_mission: bool = False


class PlanExecutionStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)


class PlanExecutionAdvanceRequest(PlanExecutionStateRequest):
    ordinal: int = Field(ge=0)
    requirement_id: int = Field(ge=1)
    result: dict[str, Any]


class PlanExecutionAbortRequest(PlanExecutionStateRequest):
    reason: str = Field(min_length=1, max_length=abort_reasons.ABORT_REASON_MAX_LENGTH)


class PlanExecutionStateResponse(BaseModel):
    execution_id: str
    standalone_plan_id: int | None = None
    item_id: int | None = None
    deployment_run_id: str | None = None
    deployment_stage: str | None = None
    deployment_member_item_id: int | None = None
    transition_id: str | None = None
    state: str
    roster_digest: str
    cursor_ordinal: int
    machine_lease_id: int | None = None
    continues_execution_id: str | None = None
    # Absent on a row written before executions carried a target: reading and
    # abandoning such a row are supported, running one is refused by name.
    execution_target: dict[str, Any] | None = None
    execution_target_digest: str | None = None

    remaining_requirement_count: int | None = None
    requirements: list[dict[str, Any]]
    results: list[dict[str, Any]]
