"""Delete one QA host registration while preserving shared custody and history."""

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    validate_test_machine_resource_name,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_reset_debt import reset_command, reset_owed
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.qa_host_turns import lock_host_turn


class TestMachineDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_machine: str


class TestMachineDeleteResponse(BaseModel):
    test_machine: str
    deleted: bool


def _refuse(code, reason, recovery):
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(
            code=code,
            message=compose_refusal(reason, recovery=recovery),
            jsonpath="$.payload",
        ),
    )


def handle_delete(request):
    try:
        parsed = TestMachineDeleteRequest(**(request.payload or {}))
        name = validate_test_machine_resource_name(parsed.test_machine)
    except (ValidationError, TestMachineCapabilityError) as exc:
        message = (
            safe_validation_message(exc)
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        return _refuse(
            "payload_invalid", message, "pass --test-machine NAME"
        )
    conn = db_helpers.connect()
    try:
        target = host_claim_target(name)
        lock_host_turn(conn, target)
        row = conn.execute(
            "SELECT 1 FROM test_machines WHERE name=%s", (name,),
        ).fetchone()
        if row is None:
            return _refuse(
                "test_machine_not_found",
                f"Test Machine {name!r} is not registered",
                "run yoke test-machine list",
            )
        if active_claim(conn, target) is not None:
            return _refuse(
                "test_machine_active_lease",
                f"Test machine {name!r} has an active lease",
                "ask the lease holder to finish or abort its QA operation, then retry deletion",
            )
        waiting = conn.execute(
            "SELECT 1 FROM qa_test_machine_waits WHERE test_machine=%s "
            "AND state IN ('waiting','reserved') LIMIT 1",
            (name,),
        ).fetchone()
        if waiting:
            return _refuse(
                "test_machine_wait_pending",
                f"Test machine {name!r} has an unsettled wait",
                "ask the waiting sessions to finish or cancel their QA work, then retry deletion",
            )
        baseline = reset_owed(conn, name)
        if baseline is not None:
            return _refuse(
                "machine_reset_owed",
                f"Test machine {name!r} owes a reset",
                reset_command(name, baseline),
            )
        conn.execute(
            "DELETE FROM test_machines WHERE name=%s", (name,),
        )
        conn.commit()
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "test_machine": name,
                "deleted": True,
            },
        )
    finally:
        conn.close()


def register(registry):
    registry.register(
        "test_machine.delete",
        handle_delete,
        TestMachineDeleteRequest,
        TestMachineDeleteResponse,
        stability="stable",
        minimum_serving_version="next-release",
        owner_module=__name__,
        target_kinds=["global"],
        side_effects=["test_machine_delete"],
        guardrails=["no_active_lease", "no_pending_wait", "no_reset_debt"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
