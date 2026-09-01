"""Deterministic admission selection across a project's QA machines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_type,
)

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_contention import ClaimContention
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    active_claim,
    acquire,
)
from yoke_core.domain.host_control_runner import (
    TestMachineContract,
    list_test_machine_contracts,
    load_test_machine_contract,
)
from yoke_core.domain.machine_qa_capability import host_claim_target
from yoke_core.domain.machine_qa_capability_rows import test_machine_capability_rows


@dataclass(frozen=True)
class BusyTestMachine:
    """One candidate whose global host claim is already held."""

    machine: str
    lease: CoordinationClaim
    contention: ClaimContention | None


@dataclass(frozen=True)
class TestMachineAdmission:
    """One acquired machine plus the operator-readable selection reason."""

    contract: TestMachineContract
    lease: CoordinationClaim
    selection_reason: str


@dataclass(frozen=True)
class _Verification:
    status: str
    error_code: str | None


class TestMachineFleetBusy(TestMachineCapabilityError):
    """Every eligible machine is already admitted to another execution."""

    def __init__(self, busy: list[BusyTestMachine]) -> None:
        names = ", ".join(candidate.machine for candidate in busy)
        super().__init__(f"all registered test machines are in use: {names}")
        self.busy = tuple(busy)


def _verification_by_machine(
    conn: Any,
    candidates: list[TestMachineContract],
) -> dict[str, _Verification]:
    if not candidates:
        return {}
    capability_rows = {
        row.machine: row
        for row in test_machine_capability_rows(
            conn,
            project_id=candidates[0].project_id,
        )
    }
    receipts: dict[str, _Verification] = {}
    from yoke_core.domain.schema_common import _table_exists

    if _table_exists(conn, "test_machine_verifications"):
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        rows = conn.execute(
            "SELECT capability_type,status,error_code "
            "FROM test_machine_verifications "
            f"WHERE project_id={marker}",
            (candidates[0].project_id,),
        ).fetchall()
        receipts = {
            str(row["capability_type"]): _Verification(
                status=str(row["status"]),
                error_code=(str(row["error_code"]) if row["error_code"] else None),
            )
            for row in rows
        }
    return {
        name: receipts.get(
            test_machine_capability_type(name),
            _Verification(
                status="verified" if row.verified_at else "configured_unverified",
                error_code=None,
            ),
        )
        for name, row in capability_rows.items()
    }


def _selection_reason(
    name: str,
    verification: _Verification,
    *,
    automatic: bool,
) -> str:
    if verification.status == "verified":
        return f"selected {name}: verified"
    basis = "fallback by name" if automatic else "explicitly required"
    if verification.status == "error":
        code = verification.error_code or "unknown"
        return f"selected {name}: {basis}, last verification error {code}"
    return f"selected {name}: {basis}, verification is not yet green"


def acquire_test_machine_admission(
    conn: Any,
    *,
    project: str,
    session_id: str,
    machine: str | None,
    select_any: bool,
) -> TestMachineAdmission:
    """Acquire a named host, or the healthiest free host then stable name."""
    automatic = machine is None and select_any
    if machine is not None or not select_any:
        candidates = [
            load_test_machine_contract(conn, project=project, machine=machine)
        ]
    else:
        candidates = list_test_machine_contracts(conn, project=project)
        if not candidates:
            raise TestMachineCapabilityError(
                f"project {project!r} has no test-machine capability"
            )
    verification = _verification_by_machine(conn, candidates)
    candidates.sort(
        key=lambda candidate: (
            verification[candidate.settings["resource_name"]].status != "verified",
            candidate.settings["resource_name"],
        )
    )
    busy: list[BusyTestMachine] = []
    for candidate in candidates:
        name = candidate.settings["resource_name"]
        target = host_claim_target(name)
        try:
            lease = acquire(
                conn,
                target,
                session_id,
                reason="machine-qa-execution",
            )
        except CoordinationClaimHeldError as exc:
            held = active_claim(conn, target)
            if held is None:
                raise TestMachineCapabilityError(
                    "test-machine lease changed while acquiring; retry execution"
                ) from None
            busy.append(BusyTestMachine(name, held, exc.contention))
            continue
        return TestMachineAdmission(
            contract=candidate,
            lease=lease,
            selection_reason=_selection_reason(
                name,
                verification[name],
                automatic=automatic,
            ),
        )
    raise TestMachineFleetBusy(busy)


def acquire_test_machine(
    conn: Any,
    *,
    project: str,
    session_id: str,
    machine: str | None,
    select_any: bool,
) -> tuple[TestMachineContract, CoordinationClaim]:
    """Acquire and return the direct-execution machine contract and lease."""
    admission = acquire_test_machine_admission(
        conn,
        project=project,
        session_id=session_id,
        machine=machine,
        select_any=select_any,
    )
    return admission.contract, admission.lease


__all__ = [
    "BusyTestMachine",
    "TestMachineAdmission",
    "TestMachineFleetBusy",
    "acquire_test_machine",
    "acquire_test_machine_admission",
]
