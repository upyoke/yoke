"""Registered reads and authority-checked operations for the Test Mac screen."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_contracts.machine_qa_execution import (
    BRIDGE_DIAGNOSE_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    RESET_OPERATION,
    VERIFY_OPERATION,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.machine_qa_capability import (
    TestMachineCapabilityError,
    replace_test_machine_settings,
    test_machine_detail,
)


#: The CLI shape that performs each operation on a credential-owning machine.
OPERATION_COMMANDS = {
    VERIFY_OPERATION: "verify",
    RESET_OPERATION: "reset",
    GOLDEN_CAPTURE_OPERATION: "golden-capture",
    BRIDGE_DIAGNOSE_OPERATION: "bridge-diagnose",
}


class TestMachineGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    machine: str | None = None


class TestMachineSettingsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    machine: str | None = None
    settings: dict[str, Any]
    base_settings: str | None = None


class TestMachineResponse(BaseModel):
    project_id: int
    project: str
    machine: str
    capability_type: str
    kind: str
    display_name: str
    runner_id: str
    settings: dict[str, str]
    settings_token: str
    features: list[str]
    host_baselines: list[str]
    host_baseline_end_states: dict[str, str]
    host_kinds: list[str]
    concurrency: dict[str, Any]
    verification: dict[str, Any]
    operations: list[dict[str, Any]]
    secrets: list[dict[str, Any]]
    active_lease: dict[str, Any] | None
    methods: list[dict[str, Any]]


class TestMachineSettingsReplaceResponse(BaseModel):
    project_id: int
    project: str
    machine: str
    capability_type: str
    settings: dict[str, str]
    settings_token: str
    verification_status: str


class TestMachineVerifyResponse(BaseModel):
    project: str
    machine: str
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
        result = test_machine_detail(
            conn,
            project=parsed.project,
            machine=parsed.machine,
        )
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
            machine=parsed.machine,
            settings=parsed.settings,
            base_settings=parsed.base_settings,
        )
    except TestMachineCapabilityError as exc:
        conn.rollback()
        return _failure("test_machine_settings_invalid", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


def handle_operation_on_control_plane(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    """Refuse an operation the control plane structurally cannot perform.

    Every operator-run operation drives a real machine over a credential that
    lives on one workstation, so the hosted control plane names the command to
    run there instead of failing as though the machine were broken.
    """
    try:
        parsed = TestMachineGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    # The operation is the function id the caller dispatched, not a payload
    # field: one refusal handler serves four ids, and each must name the
    # command the caller actually asked for.
    operation = str(request.function).rsplit(".", 1)[-1]
    command = OPERATION_COMMANDS.get(operation)
    if command is None:
        return _failure(
            "test_machine_operation_unknown",
            f"{request.function!r} is not an operator-run test-machine operation",
        )
    selector = f" --machine {parsed.machine}" if parsed.machine else ""
    return _failure(
        "host_control_client_required",
        f"test-machine {operation.replace('_', ' ')} cannot execute on "
        "the hosted control plane; run `yoke test-machine "
        f"{command} --project {parsed.project}{selector}` from a "
        "credential-owning harness or CLI machine",
    )


def _invalid(exc: ValidationError) -> HandlerOutcome:
    return _failure("payload_invalid", safe_validation_message(exc))


def _failure(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath="$.payload"),
    )


__all__ = [
    "OPERATION_COMMANDS",
    "TestMachineGetRequest",
    "TestMachineResponse",
    "TestMachineSettingsReplaceRequest",
    "TestMachineSettingsReplaceResponse",
    "TestMachineVerifyResponse",
    "handle_get",
    "handle_operation_on_control_plane",
    "handle_settings_replace",
]
