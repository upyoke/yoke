"""Registered reads and authority-checked operations for the Test Mac screen."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.test_machine_capability import (
    TestMachineCapabilityError,
    replace_test_machine_settings,
    test_machine_detail,
)


class TestMachineGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str


class TestMachineSettingsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    settings: dict[str, Any]
    base_settings: str | None = None


class TestMachineResponse(BaseModel):
    project_id: int
    project: str
    kind: str
    display_name: str
    executor_id: str
    settings: dict[str, str]
    settings_token: str
    features: list[str]
    host_baselines: list[str]
    concurrency: dict[str, Any]
    verification: dict[str, Any]
    secrets: list[dict[str, Any]]
    active_lease: dict[str, Any] | None
    methods: list[dict[str, Any]]


class TestMachineSettingsReplaceResponse(BaseModel):
    project_id: int
    project: str
    settings: dict[str, str]
    settings_token: str
    verification_status: str


class TestMachineVerifyResponse(BaseModel):
    project: str
    status: str
    checked_at: str
    checks: list[dict[str, Any]]
    error_code: str | None


def handle_get(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = test_machine_detail(conn, project=parsed.project)
    except TestMachineCapabilityError as exc:
        return _failure("test_machine_unavailable", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_settings_replace(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineSettingsReplaceRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    conn = db_helpers.connect()
    try:
        result = replace_test_machine_settings(
            conn,
            project=parsed.project,
            settings=parsed.settings,
            base_settings=parsed.base_settings,
        )
    except TestMachineCapabilityError as exc:
        conn.rollback()
        return _failure("test_machine_settings_invalid", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_verify(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_core.domain.machine_qa_execution import verify_test_machine

    conn = db_helpers.connect()
    try:
        result = verify_test_machine(
            conn,
            project=parsed.project,
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
        )
    except (TestMachineCapabilityError, ValueError) as exc:
        conn.rollback()
        return _failure("test_machine_verification_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def _invalid(exc: ValidationError) -> HandlerOutcome:
    return _failure("payload_invalid", safe_validation_message(exc))


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


__all__ = [
    "TestMachineGetRequest",
    "TestMachineResponse",
    "TestMachineSettingsReplaceRequest",
    "TestMachineSettingsReplaceResponse",
    "TestMachineVerifyResponse",
    "handle_get",
    "handle_settings_replace",
    "handle_verify",
]
