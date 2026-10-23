"""Server-side claim authority for two-phase host-control execution."""

from __future__ import annotations

from yoke_core.domain.machine_qa_lease_messages import (
    conflicting_lease,
    held_host,
    invalid_lease,
)

import hmac
from typing import Any, Sequence

from yoke_core.domain.machine_qa_submission_lease import _lock_submission_claim
from yoke_core.domain.coordination_claim_record import (
    CoordinationClaim,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimNotFoundError,
    CoordinationClaimStaleHolderError,
    release,
)
from yoke_core.domain.coordination_claim_contention import ClaimContention
from yoke_core.domain.host_control_runner import (
    TestMachineContract,
    load_test_machine_contract,
)
from yoke_core.domain.machine_qa_host_selection import (
    TestMachineFleetBusy,
    acquire_test_machine_admission,
)
from yoke_core.domain.machine_qa_execution_contract import (
    HostControlExecutionContract,
    HostControlOperation,
    issue_execution_contract,
)
from yoke_core.domain.machine_qa_capability import host_claim_key
from yoke_core.domain.host_control_submission_receipt import (
    host_control_submission_receipt,
    host_control_submission_receipt_matches,
)

HOST_CONTROL_SUBMISSION_RECEIPT_KEY = "host_control_submission"


class MachineQaProtocolError(ValueError):
    """A begin/submit request violates the issued execution contract."""


class MachineQaProtocolLeaseHeld(MachineQaProtocolError):
    """The target host is already leased by another execution."""

    def __init__(
        self,
        *,
        lease: CoordinationClaim,
        test_machine: str,
        contention: ClaimContention | None = None,
    ) -> None:
        super().__init__(held_host(lease, test_machine))
        self.lease = lease
        self.test_machine = test_machine
        self.contention = contention


class _CommitDeferredConnection:
    def __init__(self, conn: Any) -> None:
        self._connection = conn
        self._inner = getattr(conn, "_inner", conn)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass


def commit_deferred_connection(conn: Any) -> Any:
    """Adapt commit-owning leaf writers to one lease-release transaction."""
    return _CommitDeferredConnection(conn)


def _issue(
    conn: Any,
    test_machine: TestMachineContract,
    lease: CoordinationClaim,
    *,
    operation: HostControlOperation,
    checks: Sequence[str],
    baselines: Sequence[str],
    cases: Sequence[dict[str, Any]],
    golden_destination: str | None = None,
    selection_reason: str | None = None,
    plan_execution_id: str | None = None,
    continues_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> HostControlExecutionContract:
    settings = dict(test_machine.settings)
    if operation == "golden_capture":
        # Capture changes this output pointer; excluding it keeps retries stable.
        from yoke_core.domain.machine_qa_golden_destination import (
            GOLDEN_BASELINE_PATH_KEY,
        )

        settings.pop(GOLDEN_BASELINE_PATH_KEY, None)
    from yoke_core.domain.machine_qa_execution_contract import public_case_snapshots

    from yoke_core.domain.machine_reset_debt import reset_owed

    owed = reset_owed(conn, settings["resource_name"]) if cases else None
    return issue_execution_contract(
        reset_owed_baseline=owed,
        operation=operation,
        lease_id=lease.id,
        lease_key=lease.key,
        project_id=test_machine.project_id,
        project=test_machine.project,
        settings=settings,
        selection_reason=selection_reason,
        checks=list(checks),
        baselines=list(baselines),
        cases=public_case_snapshots(conn, cases),
        golden_destination=golden_destination,
        plan_execution_id=plan_execution_id,
        continues_execution_id=continues_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
    )


def begin_host_control_execution(
    conn: Any,
    *,
    project: str,
    session_id: str,
    operation: HostControlOperation,
    checks: Sequence[str] = (),
    baselines: Sequence[str] = (),
    cases: Sequence[dict[str, Any]] = (),
    golden_destination: str | None = None,
    plan_execution_id: str | None = None,
    continues_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
    test_machine: str | None = None,
    select_any: bool = True,
    healthy_only: bool = False,
    host_cases: Sequence[dict[str, Any]] | None = None,
) -> HostControlExecutionContract:
    """Validate settings and acquire the serial host claim."""
    if not str(session_id or "").strip():
        raise MachineQaProtocolError(
            "host-control execution requires an owning session"
        )
    if any((case.get("method_config") or {}).get("test_machines") for case in cases):
        raise MachineQaProtocolError(
            "test_machine_set_requires_plan: run this simultaneous-host case "
            "through yoke qa plan run so every declared host is leased together"
        )
    try:
        admission = acquire_test_machine_admission(
            conn,
            project=project,
            session_id=session_id,
            test_machine=test_machine,
            select_any=select_any,
            healthy_only=healthy_only,
            cases=tuple(host_cases if host_cases is not None else cases),
        )
    except CoordinationClaimStaleHolderError as exc:
        raise MachineQaProtocolError(str(exc)) from None
    except TestMachineFleetBusy as exc:
        held = exc.busy[0]
        raise MachineQaProtocolLeaseHeld(
            lease=held.lease,
            test_machine=held.test_machine,
            contention=held.contention,
        ) from None
    return _issue(
        conn,
        admission.contract,
        admission.lease,
        operation=operation,
        checks=checks,
        baselines=baselines,
        cases=cases,
        golden_destination=golden_destination,
        selection_reason=admission.selection_reason,
        plan_execution_id=plan_execution_id,
        continues_execution_id=continues_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
    )


def _validate_lease_owner(
    conn: Any,
    *,
    project: str,
    session_id: str,
    actor_id: str | None,
    lease_id: int,
    allow_released: bool,
) -> tuple[CoordinationClaim, TestMachineContract]:
    try:
        lease = _lock_submission_claim(conn, int(lease_id))
    except CoordinationClaimNotFoundError as exc:
        raise MachineQaProtocolError(
            invalid_lease(lease_id, "no lease was issued with that id")
        ) from exc
    machine_id = lease.target.test_machine
    if machine_id is None:
        raise MachineQaProtocolError(
            invalid_lease(lease_id, "it does not name a machine")
        )
    test_machine = load_test_machine_contract(
        conn,
        project=project,
        test_machine=machine_id,
    )
    resource_name = test_machine.settings["resource_name"]
    if lease.is_active and lease.key != host_claim_key(resource_name):
        raise MachineQaProtocolError(
            conflicting_lease(
                lease, resource_name, "the lease names a different target"
            )
        )
    if lease.session_id != str(session_id or ""):
        raise MachineQaProtocolError(
            conflicting_lease(lease, resource_name, "a different session owns it")
        )
    expected_actor = str(lease.actor_id) if lease.actor_id is not None else None
    submitted_actor = str(actor_id) if actor_id is not None else None
    if expected_actor != submitted_actor:
        raise MachineQaProtocolError(
            conflicting_lease(lease, resource_name, "a different actor owns it")
        )
    if not lease.is_active and not allow_released:
        raise MachineQaProtocolError(
            conflicting_lease(lease, resource_name, "the lease is no longer active")
        )
    return lease, test_machine


def validate_host_control_submission(
    conn: Any,
    *,
    project: str,
    session_id: str,
    actor_id: str | None,
    lease_id: int,
    contract_digest: str,
    operation: HostControlOperation,
    checks: Sequence[str] = (),
    baselines: Sequence[str] = (),
    cases: Sequence[dict[str, Any]] = (),
    golden_destination: str | None = None,
    allow_recorded_replay: bool = False,
    plan_execution_id: str | None = None,
    continues_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> tuple[CoordinationClaim, HostControlExecutionContract]:
    """Lock the lease and validate actor, target, and issued contract."""
    lease, test_machine = _validate_lease_owner(
        conn,
        project=project,
        session_id=session_id,
        actor_id=actor_id,
        lease_id=lease_id,
        allow_released=allow_recorded_replay,
    )
    expected = _issue(
        conn,
        test_machine,
        lease,
        operation=operation,
        checks=checks,
        baselines=baselines,
        cases=cases,
        golden_destination=golden_destination,
        plan_execution_id=plan_execution_id,
        continues_execution_id=continues_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
    )
    if lease.is_active and not hmac.compare_digest(
        expected.contract_digest,
        str(contract_digest),
    ):
        from yoke_core.domain.machine_reset_debt import recovered_submission_contract

        recovered = (
            recovered_submission_contract(conn, lease.id, contract_digest, expected)
            if allow_recorded_replay
            else None
        )
        if recovered is None:
            raise MachineQaProtocolError(
                "host-control target changed after execution began"
            )
        expected = recovered
    return lease, expected


def complete_host_control_execution(
    conn: Any,
    lease: CoordinationClaim,
    *,
    reason: str,
) -> None:
    """Release a successfully recorded execution's claim."""
    release(conn, lease.id, reason, canonical_reason="completed")


__all__ = [
    "HOST_CONTROL_SUBMISSION_RECEIPT_KEY",
    "MachineQaProtocolError",
    "MachineQaProtocolLeaseHeld",
    "begin_host_control_execution",
    "commit_deferred_connection",
    "complete_host_control_execution",
    "host_control_submission_receipt",
    "host_control_submission_receipt_matches",
    "validate_host_control_submission",
]
