"""Lease-authorized writes to Test Machine power ownership."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.machine_config.test_machine import validate_test_machine_resource_name
from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    CoordinationClaimStaleHolderError,
    acquire,
    active_claim,
)
from yoke_core.domain.handlers.machine_qa import _failure, _invalid
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.qa_host_holdover import DIRECT_OPERATION_REASON
from yoke_core.domain.qa_host_turns import lock_host_turn


class TestMachinePowerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_machine: str


class TestMachinePowerResponse(BaseModel):
    test_machine: str
    yoke_started: bool


def handle_power(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachinePowerRequest.model_validate(request.payload)
    except ValidationError as exc:
        return _invalid(exc)
    try:
        name = validate_test_machine_resource_name(parsed.test_machine)
    except ValueError as exc:
        return _failure("test_machine_invalid", str(exc))

    target = host_claim_target(name)
    started = request.function == "test_machine.power_started"
    conn: Any = db_helpers.connect()
    try:
        lock_host_turn(conn, target)
        lease = active_claim(conn, target)
        if lease is None or lease.session_id != request.actor.session_id:
            return _failure(
                "test_machine_power_lease_required",
                f"hold the lease for {name} before recording its power state",
            )
        marked_at = db_helpers.instant_parameter(conn, db_helpers.utc_now()) if started else None
        updated = conn.execute(
            "UPDATE test_machines SET yoke_started_at=%s WHERE name=%s",
            (marked_at, name),
        )
        if updated.rowcount != 1:
            return _failure(
                "test_machine_not_found",
                f"{name} is unregistered; run yoke test-machine list",
            )
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True, result_payload={"test_machine": name, "yoke_started": started}
    )


class TestMachineLeaseResponse(BaseModel):
    claim_id: int


def handle_lease(request: FunctionCallRequest) -> HandlerOutcome:
    try:
        parsed = TestMachinePowerRequest.model_validate(request.payload)
        target = host_claim_target(parsed.test_machine)
    except ValidationError as exc:
        return _invalid(exc)
    except ValueError as exc:
        return _failure("test_machine_invalid", str(exc))
    conn = db_helpers.connect()
    try:
        lock_host_turn(conn, target)
        if conn.execute(
            "SELECT 1 FROM test_machines WHERE name=%s", (target.test_machine,)
        ).fetchone() is None:
            return _failure(
                "test_machine_not_found",
                f"{target.test_machine} is unregistered; run yoke test-machine list",
            )
        claim = acquire(
            conn, target, request.actor.session_id, reason=DIRECT_OPERATION_REASON
        )
    except CoordinationClaimHeldError as exc:
        code = "claim_stale_holder" if isinstance(exc, CoordinationClaimStaleHolderError) else "claim_held"
        return _failure(code, str(exc))
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload={"claim_id": claim.id})


def register(registry) -> None:
    registry.register(
        "test_machine.lease_acquire",
        handle_lease,
        TestMachinePowerRequest,
        TestMachineLeaseResponse,
        stability="stable",
        minimum_serving_version="next-release",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["test_machine_lease_acquire"],
        guardrails=["exclusive_host_lease"],
        adapter_status="internal",
        claim_required_kind=None,
    )
    for function in ("test_machine.power_started", "test_machine.power_stopped"):
        registry.register(
            function,
            handle_power,
            TestMachinePowerRequest,
            TestMachinePowerResponse,
            stability="stable",
            minimum_serving_version="next-release",
            owner_module=__name__,
            target_kinds=["global"],
            side_effects=["test_machine_power_ownership_write"],
            guardrails=["current_test_machine_lease"],
            adapter_status="internal",
            claim_required_kind=None,
        )
