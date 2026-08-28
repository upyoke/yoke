"""Registered reads and authority-checked operations for the Test Mac screen."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
)
from yoke_core.domain.machine_qa_submission_artifacts import (
    ensure_secret_free_result,
)
from yoke_core.domain.machine_qa_capability import (
    TestMachineCapabilityError,
    replace_test_machine_settings,
    test_machine_detail,
)


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
    concurrency: dict[str, Any]
    verification: dict[str, Any]
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


class TestMachineVerifyBeginRequest(TestMachineGetRequest):
    pass


class TestMachineVerifyBeginResponse(BaseModel):
    execution: HostControlExecutionContract


class TestMachineVerifySubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    status: Literal["verified", "error"]
    checks: list[dict[str, Any]]
    error_code: str | None = None


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


def handle_verify(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineGetRequest(**(request.payload or {}))
    except ValidationError as exc:
        return _invalid(exc)
    selector = f" --machine {parsed.machine}" if parsed.machine else ""
    return _failure(
        "host_control_client_required",
        "test-machine verification cannot execute on the hosted control "
        "plane; run `yoke test-machine verify --project "
        f"{parsed.project}{selector}` from a credential-owning harness or CLI machine",
    )


def handle_verify_begin(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineVerifyBeginRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        begin_host_control_execution,
    )

    conn = db_helpers.connect()
    try:
        contract = begin_host_control_execution(
            conn,
            project=parsed.project,
            session_id=request.actor.session_id,
            machine=parsed.machine,
            select_any=False,
            operation="verify",
            checks=("connection", "terminal_bridge"),
            baselines=("fresh-host", "shell-preconfigured"),
        )
    except (MachineQaProtocolError, TestMachineCapabilityError) as exc:
        conn.rollback()
        return _failure("test_machine_verification_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "execution": contract.model_dump(mode="json"),
        },
    )


def _validate_verification_result(
    parsed: TestMachineVerifySubmitRequest,
    contract: HostControlExecutionContract,
) -> None:
    expected_names = [*contract.checks, *contract.baselines]
    observed_names: list[str] = []
    observed_ok: list[bool] = []
    for check in parsed.checks:
        if not isinstance(check.get("name"), str):
            raise ValueError("verification check is missing its registered name")
        if not isinstance(check.get("ok"), bool):
            raise ValueError("verification check is missing its boolean result")
        observed_names.append(str(check["name"]))
        observed_ok.append(bool(check["ok"]))
    if not observed_names or observed_names != expected_names[: len(observed_names)]:
        raise ValueError(
            "verification result does not follow the issued check sequence"
        )
    if parsed.status == "verified":
        if (
            observed_names != expected_names
            or not all(observed_ok)
            or parsed.error_code is not None
        ):
            raise ValueError("verified result must pass every issued check")
    elif (
        not str(parsed.error_code or "").strip()
        or not all(observed_ok[:-1])
        or observed_ok[-1]
    ):
        raise ValueError("error result must identify its first failed check")
    ensure_secret_free_result(parsed.model_dump(mode="json"))


def handle_verify_submit(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachineVerifySubmitRequest.model_validate(
            request.payload or {},
        )
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        commit_deferred_connection,
        complete_host_control_execution,
        validate_host_control_submission,
    )
    from yoke_core.domain.machine_verification_recording import (
        record_test_machine_verification,
        recorded_test_machine_verification,
    )

    conn = db_helpers.connect()
    try:
        lease, contract = validate_host_control_submission(
            conn,
            project=parsed.project,
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            operation="verify",
            checks=("connection", "terminal_bridge"),
            baselines=("fresh-host", "shell-preconfigured"),
            allow_recorded_replay=True,
        )
        _validate_verification_result(parsed, contract)
        recorded = recorded_test_machine_verification(
            conn,
            contract.project_id,
            machine=contract.settings["resource_name"],
            lease_id=lease.id,
            contract_digest=parsed.contract_digest,
        )
        if recorded is None:
            if not lease.is_active:
                raise ValueError(
                    "host-control lease is released without a recorded verification"
                )
            recorded = record_test_machine_verification(
                commit_deferred_connection(conn),
                contract.project_id,
                machine=contract.settings["resource_name"],
                status=parsed.status,
                checks=parsed.checks,
                error_code=parsed.error_code,
                lease_id=lease.id,
                contract_digest=parsed.contract_digest,
            )
        if lease.is_active:
            complete_host_control_execution(
                conn,
                lease,
                reason="test-machine-verification-complete",
            )
        else:
            conn.commit()
        result = {
            "project": contract.project,
            "machine": contract.settings["resource_name"],
            **recorded,
        }
    except (
        MachineQaProtocolError,
        TestMachineCapabilityError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_verification_submit_failed", str(exc))
    except Exception:
        conn.rollback()
        raise
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
    "TestMachineVerifyBeginRequest",
    "TestMachineVerifyBeginResponse",
    "TestMachineVerifyResponse",
    "TestMachineVerifySubmitRequest",
    "handle_get",
    "handle_settings_replace",
    "handle_verify",
    "handle_verify_begin",
    "handle_verify_submit",
]
