"""Two-phase authority for every operator-run test-machine operation.

Begin takes the machine's lease and issues a digest-bound contract; the
credential-owning client executes it; submit validates the result against the
contract it issued and records the receipt. One pair serves verify, reset,
golden capture, and bridge diagnosis, because the authority question is
identical for all four and four copies of it would drift.

Where the receipt lands is the one thing that differs. Verification decides
whether the machine is usable at all, so it writes the verification row every
availability surface reads; the other three record what was last done to the
machine without touching its readiness.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_contracts.machine_qa_execution import (
    GOLDEN_CAPTURE_OPERATION,
    HostControlExecutionContract,
    HostControlOperation,
    VERIFY_OPERATION,
)
from yoke_contracts.test_machine_verification_surfaces import verification_surfaces
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers.machine_qa import _failure, _invalid
from yoke_core.domain.handlers.machine_qa_operation_result import (
    validate_operation_result,
)
from yoke_core.domain.machine_qa_capability import TestMachineCapabilityError
from yoke_core.domain.machine_qa_submission_artifacts import MachineQaSubmissionArtifact
from yoke_core.domain.handlers.machine_qa_operation_receipt import (
    performed_at_row,
    record_capture_destination,
    record_operation_receipt,
    recorded_operation_receipt,
)
from yoke_core.domain.machine_qa_golden_destination import (
    resolve_golden_capture_destination,
    selected_test_machine_row,
)
from yoke_core.domain.machine_qa_operation_shape import (
    TestMachineOperationShapeError,
    operation_contract_shape,
)
from yoke_core.domain.machine_qa_operation_lease import (
    begin_operation_execution,
    finish_operation_execution,
    operation_mission,
    repeated_mission_receipt,
)


OperatorOperation = Literal[
    "verify", "reset", "golden_capture", "bridge_diagnose", "screenshot"
]


class TestMachineOperationBeginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    machine: str | None = None
    operation: OperatorOperation
    baseline: str | None = None
    destination: str | None = None


class TestMachineOperationBeginResponse(BaseModel):
    execution: HostControlExecutionContract


class TestMachineOperationSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project: str
    lease_id: int = Field(ge=1)
    contract_digest: str = Field(min_length=1)
    operation: OperatorOperation
    # The issued shape, echoed back so submit rebuilds the same contract it
    # compares against. A wrong echo fails that comparison rather than being
    # taken on trust.
    baseline: str | None = None
    destination: str | None = None
    status: Literal["verified", "error"]
    checks: list[dict[str, Any]]
    error_code: str | None = None
    artifacts: list[MachineQaSubmissionArtifact] = Field(default_factory=list)


class TestMachineOperationResponse(BaseModel):
    project: str
    machine: str
    operation: str
    status: str
    performed_at: str
    checks: list[dict[str, Any]]
    error_code: str | None
    golden_baseline_path: str | None = None
    surfaces: dict[str, dict[str, Any]] | None = None


def _operation(operation: str) -> HostControlOperation:
    return operation  # type: ignore[return-value]


def refuse_browser_profile_capture(payload: Any) -> HandlerOutcome | Any:
    """Name the removed sealed browser-profile capture instead of a schema error.

    Clients that predate live browser identities send a capture component on
    golden capture: a named component gets the reason and its replacement, and
    the null they send on every ordinary operation is dropped so it proceeds.
    Returns the refusal, or the payload to validate.
    """
    if not isinstance(payload, dict) or "capture_component" not in payload:
        return payload
    if payload["capture_component"] is not None:
        return _failure(
            "browser_profile_capture_removed",
            "sealed browser-profile capture was removed: browser sign-in "
            "sessions are never sealed or restored as copies; keep a live "
            "identity instead with `yoke browser authorize --identity NAME` "
            "on the host, and upgrade this client",
        )
    return {key: value for key, value in payload.items() if key != "capture_component"}


def handle_operation_begin(request: FunctionCallRequest) -> HandlerOutcome:
    """Take the machine's lease and issue the contract for one operation."""
    payload = refuse_browser_profile_capture(request.payload)
    if isinstance(payload, HandlerOutcome):
        return payload
    try:
        parsed = TestMachineOperationBeginRequest.model_validate(payload or {})
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
    )

    conn = db_helpers.connect()
    try:
        destination = parsed.destination
        if parsed.operation == GOLDEN_CAPTURE_OPERATION:
            destination = resolve_golden_capture_destination(
                selected_test_machine_row(
                    conn, project=parsed.project, machine=parsed.machine
                ),
                requested=parsed.destination,
            )
        contract = begin_operation_execution(
            conn,
            project=parsed.project,
            actor=request.actor,
            machine=parsed.machine,
            operation=_operation(parsed.operation),
            **operation_contract_shape(
                parsed.operation,
                baseline=parsed.baseline,
                golden_destination=destination,
            ),
        )
    except (
        MachineQaProtocolError,
        TestMachineCapabilityError,
        TestMachineOperationShapeError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_operation_failed", str(exc))
    finally:
        conn.close()
    return HandlerOutcome(
        primary_success=True,
        result_payload={"execution": contract.model_dump(mode="json")},
    )


def handle_operation_submit(request: FunctionCallRequest) -> HandlerOutcome:
    """Validate one executed operation's result and record its receipt."""
    payload = refuse_browser_profile_capture(request.payload)
    if isinstance(payload, HandlerOutcome):
        return payload
    try:
        parsed = TestMachineOperationSubmitRequest.model_validate(payload or {})
    except ValidationError as exc:
        return _invalid(exc)
    from yoke_core.domain.machine_qa_execution_protocol import (
        MachineQaProtocolError,
        commit_deferred_connection,
        validate_host_control_submission,
    )

    conn = db_helpers.connect()
    try:
        mission = operation_mission(
            conn, lease_id=parsed.lease_id, project=parsed.project, actor=request.actor
        )
        lease, contract = validate_host_control_submission(
            conn,
            project=parsed.project,
            session_id=request.actor.session_id,
            actor_id=request.actor.actor_id,
            lease_id=parsed.lease_id,
            contract_digest=parsed.contract_digest,
            operation=_operation(parsed.operation),
            allow_recorded_replay=True,
            **operation_contract_shape(
                parsed.operation,
                baseline=parsed.baseline,
                golden_destination=parsed.destination,
            ),
        )
        validate_operation_result(parsed, contract)
        machine = contract.settings["resource_name"]
        recorded = recorded_operation_receipt(
            conn,
            parsed=parsed,
            contract=contract,
            lease_id=lease.id,
            machine=machine,
        )
        recorded = repeated_mission_receipt(parsed, recorded, mission)
        if recorded is not None:
            if parsed.operation == "screenshot":
                from yoke_core.domain.handlers.machine_qa_screenshot_artifact import (
                    replay_screenshot,
                )

                replay_screenshot(parsed, recorded)
            if any(
                recorded[key] != getattr(parsed, key)
                for key in ("status", "checks", "error_code")
            ):
                raise ValueError("replayed result differs from the recorded receipt")
        if recorded is None:
            if not lease.is_active:
                raise ValueError(
                    "host-control lease is released without a recorded receipt"
                )
            if parsed.operation == "screenshot":
                from yoke_core.domain.handlers.machine_qa_screenshot_artifact import (
                    store_screenshot,
                )
                from yoke_core.domain.qa_artifact_storage import ArtifactStorageError

                try:
                    store_screenshot(conn, parsed, contract)
                except ArtifactStorageError as exc:
                    conn.rollback()
                    return _failure(
                        exc.code,
                        str(exc)
                        + "; repair the configured QA artifact store and retry screenshot",
                    )
            recorded = record_operation_receipt(
                commit_deferred_connection(conn),
                parsed=parsed,
                contract=contract,
                lease_id=lease.id,
                machine=machine,
            )
        golden_baseline_path = (
            record_capture_destination(
                conn, contract=contract, parsed=parsed, machine=machine
            )
            if lease.is_active
            else (
                contract.golden_destination
                if parsed.operation == GOLDEN_CAPTURE_OPERATION
                and parsed.status == "verified"
                else None
            )
        )
        if lease.is_active:
            finish_operation_execution(
                conn,
                lease,
                mission=mission,
                reason=f"test-machine-{parsed.operation.replace('_', '-')}-complete",
            )
        else:
            conn.commit()
        result = {
            "project": contract.project,
            "machine": machine,
            "golden_baseline_path": golden_baseline_path,
            **performed_at_row(recorded),
        }
        if parsed.operation == VERIFY_OPERATION:
            result["surfaces"] = verification_surfaces(
                recorded["checks"],
                project=contract.project,
                machine=machine,
            )
    except (
        MachineQaProtocolError,
        TestMachineCapabilityError,
        TestMachineOperationShapeError,
        ValueError,
    ) as exc:
        conn.rollback()
        return _failure("test_machine_operation_submit_failed", str(exc))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return HandlerOutcome(primary_success=True, result_payload=result)


__all__ = [
    "OperatorOperation",
    "TestMachineOperationBeginRequest",
    "TestMachineOperationBeginResponse",
    "TestMachineOperationResponse",
    "TestMachineOperationSubmitRequest",
    "handle_operation_begin",
    "handle_operation_submit",
    "refuse_browser_profile_capture",
]
