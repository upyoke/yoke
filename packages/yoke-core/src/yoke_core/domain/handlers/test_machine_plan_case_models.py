"""Request and response contracts for plan-scoped Machine QA cases."""

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


class TestMachinePlanCaseBeginResponse(BaseModel):
    state: Literal["ready", "waiting"]
    execution_id: str
    cursor_ordinal: int
    execution: HostControlExecutionContract | None = None


class TestMachinePlanCaseSubmitRequest(TestMachinePlanCaseBeginRequest):
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    results: list[MachineCaseSubmissionResult]


class TestMachinePlanCaseSubmitResponse(BaseModel):
    execution_id: str
    cursor_ordinal: int
    result: dict[str, Any]


__all__ = [
    "TestMachinePlanCaseBeginRequest",
    "TestMachinePlanCaseBeginResponse",
    "TestMachinePlanCaseSubmitRequest",
    "TestMachinePlanCaseSubmitResponse",
]
