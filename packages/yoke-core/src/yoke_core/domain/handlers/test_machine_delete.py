"""Delete one QA host registration while preserving shared custody and history."""

from pydantic import BaseModel, ConfigDict, ValidationError

from yoke_contracts.api.function_call import FunctionError, HandlerOutcome
from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_type,
    validate_test_machine_resource_name,
)
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain import db_helpers
from yoke_core.domain.coordination_claims import active_claim
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_reset_debt import reset_command, reset_owed
from yoke_core.domain.project_identity import resolve_project
from yoke_core.domain.pydantic_validation_safety import safe_validation_message
from yoke_core.domain.qa_host_turns import lock_host_turn


class TestMachineDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str
    test_machine: str


class TestMachineDeleteResponse(BaseModel):
    project_id: int
    project: str
    test_machine: str
    capability_type: str
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
            "payload_invalid", message, "pass --project P --test-machine NAME"
        )
    conn = db_helpers.connect()
    try:
        identity = resolve_project(conn, parsed.project, required=False)
        if identity is None:
            return _refuse(
                "project_not_found", "Project was not found", "run yoke projects list"
            )
        cap_type = test_machine_capability_type(name)
        target = host_claim_target(name)
        lock_host_turn(conn, target)
        row = conn.execute(
            "SELECT 1 FROM project_capabilities WHERE project_id=%s AND type=%s",
            (identity.id, cap_type),
        ).fetchone()
        if row is None:
            return _refuse(
                "test_machine_not_found",
                f"Test machine {name!r} is not registered on this project",
                f"run yoke test-machine list --project {identity.slug}",
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
                reset_command(identity.slug, name, baseline),
            )
        conn.execute(
            "DELETE FROM project_capabilities WHERE project_id=%s AND type=%s",
            (identity.id, cap_type),
        )
        # Removing a successful reset receipt must not expose another project's debt.
        baseline = reset_owed(conn, name)
        if baseline is not None:
            conn.rollback()
            return _refuse(
                "machine_reset_owed",
                "Deletion would expose shared reset debt",
                reset_command(identity.slug, name, baseline),
            )
        conn.commit()
        return HandlerOutcome(
            primary_success=True,
            result_payload={
                "project_id": identity.id,
                "project": identity.slug,
                "test_machine": name,
                "capability_type": cap_type,
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
        side_effects=["project_capability_write"],
        guardrails=["no_active_lease", "no_pending_wait", "no_reset_debt"],
        adapter_status="live",
        claim_required_kind=None,
        ambient_session_required=False,
    )
