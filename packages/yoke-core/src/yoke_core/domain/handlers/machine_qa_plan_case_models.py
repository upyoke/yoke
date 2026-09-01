"""Request and response contracts for plan-scoped machine-QA cases."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_submission_recording import (
    MachineCaseSubmissionResult,
)


class TestMachinePlanCaseBeginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    ordinal: int = Field(ge=0)
    requirement_id: int = Field(ge=1)
    machine: str | None = None


class TestMachinePlanCaseBeginResponse(BaseModel):
    state: Literal["ready", "waiting"]
    execution_id: str
    cursor_ordinal: int
    execution: HostControlExecutionContract | None = None
    lease_context: dict[str, Any] | None = None
    selection_new: bool = False


class TestMachinePlanCaseSubmitRequest(TestMachinePlanCaseBeginRequest):
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    results: list[MachineCaseSubmissionResult]


class TestMachinePlanCaseSubmitResponse(BaseModel):
    execution_id: str
    cursor_ordinal: int
    result: dict[str, Any]


class AgentMissionPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline: str | None = None
    ok: bool
    error_code: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


class AgentMissionPlanCaseReadyRequest(TestMachinePlanCaseBeginRequest):
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    preparation: AgentMissionPreparation


class AgentMissionPlanCaseReadyResponse(BaseModel):
    execution_id: str
    cursor_ordinal: int
    result: dict[str, Any]


class AgentMissionAccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_id: str = Field(min_length=1)
    requirement_id: int = Field(ge=1)


class AgentMissionAccessResponse(BaseModel):
    execution_id: str
    requirement_id: int
    execution: HostControlExecutionContract


__all__ = [
    "AgentMissionAccessRequest",
    "AgentMissionAccessResponse",
    "AgentMissionPlanCaseReadyRequest",
    "AgentMissionPlanCaseReadyResponse",
    "AgentMissionPreparation",
    "TestMachinePlanCaseBeginRequest",
    "TestMachinePlanCaseBeginResponse",
    "TestMachinePlanCaseSubmitRequest",
    "TestMachinePlanCaseSubmitResponse",
]
