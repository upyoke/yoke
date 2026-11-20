"""Deterministic admission selection across the universe's QA machines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoke_contracts.machine_config.test_machine import (
    TestMachineCapabilityError,
    test_machine_capability_tags,
)

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


@dataclass(frozen=True)
class BusyTestMachine:
    """One candidate whose global host claim is already held."""

    test_machine: str
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
        names = ", ".join(candidate.test_machine for candidate in busy)
        super().__init__(f"all registered test machines are in use: {names}")
        self.busy = tuple(busy)

    def shortest_line(self, conn: Any, session_id: str) -> BusyTestMachine:
        """The busy host with the fewest other waiters; ties go by name.

        The refused session's own wait does not lengthen a line, so a
        queued waiter is not pushed off its host by its own place in it.
        """
        from yoke_core.domain.qa_host_turns import host_line

        def others(candidate: BusyTestMachine) -> int:
            line = host_line(conn, candidate.test_machine)
            return sum(1 for wait in line if wait["session_id"] != session_id)

        return min(
            self.busy, key=lambda candidate: (others(candidate), candidate.test_machine)
        )


class TestMachineHostUnhealthy(TestMachineCapabilityError):
    """Every eligible free machine last failed verification; plans queue."""

    #: Every host the refused plan case needs; its plan waits on all of them.
    test_machines: tuple[str, ...] = ()

    def __init__(self, health: dict[str, Any]) -> None:
        from yoke_core.domain.qa_host_health import unhealthy_rationale

        super().__init__(unhealthy_rationale(health))
        self.test_machine = str(health["test_machine"])
        self.health = health


def _verification_by_machine(
    conn: Any,
    candidates: list[TestMachineContract],
) -> dict[str, _Verification]:
    if not candidates:
        return {}
    names = {candidate.settings["resource_name"] for candidate in candidates}
    rows = conn.execute(
        "SELECT m.name, m.verified_at, v.status, v.error_code "
        "FROM test_machines m LEFT JOIN test_machine_verifications v "
        "ON v.test_machine_id=m.id"
    ).fetchall()
    return {
        name: _Verification(
            status=status or ("verified" if verified_at else "configured_unverified"),
            error_code=error_code,
        )
        for name, verified_at, status, error_code in rows
        if name in names
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
    test_machine: str | None,
    select_any: bool,
    healthy_only: bool = False,
    require_verified: bool = True,
    cases: tuple[dict[str, Any], ...] = (),
) -> TestMachineAdmission:
    """Acquire a named host or the first verified, healthy available match.

    *healthy_only* is a scoped plan's admission: an unhealthy host is skipped
    so its waiters stay queued until a verify or golden capture heals it.
    Operator operations admit unverified hosts so they can establish readiness.
    """
    from yoke_core.domain.qa_host_health import host_unhealthy

    automatic = test_machine is None and select_any
    if test_machine is not None or not select_any:
        candidates = [
            load_test_machine_contract(conn, project=project, test_machine=test_machine)
        ]
    else:
        candidates = list_test_machine_contracts(conn, project=project)
    from yoke_core.domain.machine_qa_case_platform import (
        matching_platform_hosts,
        required_host_tags,
    )

    candidates = matching_platform_hosts(candidates, cases)
    if not candidates:
        raise TestMachineCapabilityError(
            "no eligible Test Machine is registered; "
            "register and verify a Test Machine before retrying"
        )
    tags = required_host_tags(cases)
    if tags:
        candidates = [
            candidate for candidate in candidates
            if tags.issubset(test_machine_capability_tags(candidate.settings))
        ]
        if not candidates:
            raise TestMachineCapabilityError(
                "test_machine_capability_tags_unavailable: QA requires "
                f"{', '.join(sorted(tags))}; select a Test Machine with "
                "the required capability_tags or correct the case's declared tags"
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
    unverified: list[str] = []
    for candidate in candidates:
        name = candidate.settings["resource_name"]
        target = host_claim_target(name)
        verified_only = automatic and require_verified
        health = host_unhealthy(conn, name) if healthy_only or verified_only else None
        if health is not None:
            unhealthy.append(health)
            continue
        if verified_only and verification[name].status != "verified":
            unverified.append(name)
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
    if busy:
        raise TestMachineFleetBusy(busy)
    if unhealthy:
        raise TestMachineHostUnhealthy(unhealthy[0])
    raise TestMachineCapabilityError(
        "test_machine_no_verified_host: no matching Test Machine has verified readiness "
        f"({', '.join(unverified)}); run yoke test-machine verify --test-machine NAME "
        "for a matching host, then retry QA"
    )


def acquire_test_machine(
    conn: Any,
    *,
    project: str,
    session_id: str,
    test_machine: str | None,
    select_any: bool,
) -> tuple[TestMachineContract, CoordinationClaim]:
    """Acquire and return the direct-execution machine contract and lease."""
    admission = acquire_test_machine_admission(
        conn,
        project=project,
        session_id=session_id,
        test_machine=test_machine,
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
