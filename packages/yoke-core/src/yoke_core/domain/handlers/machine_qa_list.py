"""Registered read returning every test machine for one project."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers.machine_qa import TestMachineResponse, _failure
from yoke_core.domain.machine_qa_capability import (
    TestMachineCapabilityError,
    test_machine_list,
)
from yoke_core.domain.pydantic_validation_safety import safe_validation_message


class TestMachineListRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str


class TestMachineListResponse(BaseModel):
    project_id: int
    project: str
    machines: list[TestMachineResponse]


def handle_list(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineListRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _failure("payload_invalid", safe_validation_message(exc))
    conn = db_helpers.connect()
    try:
        result = test_machine_list(conn, project=parsed.project)
    except TestMachineCapabilityError as exc:
        return _failure("test_machine_unavailable", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "TestMachineListRequest",
    "TestMachineListResponse",
    "handle_list",
]
