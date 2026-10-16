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


class TestMachineHostUnhealthy(TestMachineCapabilityError):
    """Every eligible free machine last failed verification; plans queue."""

    def __init__(self, health: dict[str, Any]) -> None:
        from yoke_core.domain.qa_host_health import unhealthy_rationale

        super().__init__(unhealthy_rationale(health))
        self.machine = str(health["machine"])
        self.health = health


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
    healthy_only: bool = False,
) -> TestMachineAdmission:
    """Acquire a named host, or the healthiest free host then stable name.

    *healthy_only* is a scoped plan's admission: an unhealthy host is skipped
    so its waiters stay queued until a verify or golden capture heals it.
    Operator operations admit it, because they are what heals it.
    """
    from yoke_core.domain.qa_host_health import host_unhealthy

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
    unhealthy: list[dict[str, Any]] = []
    for candidate in candidates:
        name = candidate.settings["resource_name"]
        target = host_claim_target(name)
        health = host_unhealthy(conn, name) if healthy_only else None
        if health is not None:
            unhealthy.append(health)
            continue
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
    if busy or not unhealthy:
        raise TestMachineFleetBusy(busy)
    raise TestMachineHostUnhealthy(unhealthy[0])


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
    "TestMachineHostUnhealthy",
    "acquire_test_machine",
    "acquire_test_machine_admission",
]
