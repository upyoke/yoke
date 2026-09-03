"""Server-side claim authority for two-phase host-control execution."""

from __future__ import annotations

import hmac
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.coordination_claim_record import (
    FROM_CLAUSE,
    SELECT_COLUMNS,
    CoordinationClaim,
    row_to_claim,
)
from yoke_core.domain.coordination_claims import (
    CoordinationClaimNotFoundError,
    CoordinationClaimStaleHolderError,
    get_claim,
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
from yoke_core.domain.machine_qa_capability import (
    host_claim_key,
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
        machine: str,
        contention: ClaimContention | None = None,
    ) -> None:
        super().__init__(f"test machine {machine!r} is in use by another execution")
        self.lease = lease
        self.machine = machine
        self.contention = contention


class _CommitDeferredConnection:
    """Delegate SQL while reserving commit/rollback for the submit handler."""

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


def host_control_submission_receipt(
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any]:
    """Return the durable identity shared by result and verification records."""
    return {
        "lease_id": int(lease_id),
        "contract_digest": str(contract_digest),
    }


def host_control_submission_receipt_matches(
    value: Any,
    *,
    lease_id: int,
    contract_digest: str,
) -> bool:
    """Return whether a stored receipt identifies this issued submission."""
    if not isinstance(value, Mapping):
        return False
    try:
        stored_lease_id = int(value.get("lease_id"))
    except (TypeError, ValueError):
        return False
    stored_digest = value.get("contract_digest")
    return (
        stored_lease_id == int(lease_id)
        and isinstance(stored_digest, str)
        and hmac.compare_digest(stored_digest, str(contract_digest))
    )


def _lock_submission_claim(conn: Any, claim_id: int) -> CoordinationClaim:
    if not db_backend.connection_is_postgres(conn):
        if not bool(getattr(conn, "in_transaction", False)):
            conn.execute("BEGIN IMMEDIATE")
        return get_claim(conn, claim_id)
    marker = "%s"
    row = conn.execute(
        f"SELECT {SELECT_COLUMNS} {FROM_CLAUSE} WHERE wc.id={marker} FOR UPDATE OF wc",
        (claim_id,),
    ).fetchone()
    if row is None:
        raise CoordinationClaimNotFoundError(
            f"Coordination claim id={claim_id} not found"
        )
    return row_to_claim(row)


def _issue(
    machine: TestMachineContract,
    lease: CoordinationClaim,
    *,
    operation: HostControlOperation,
    checks: Sequence[str],
    baselines: Sequence[str],
    cases: Sequence[dict[str, Any]],
    golden_destination: str | None = None,
    selection_reason: str | None = None,
    plan_execution_id: str | None = None,
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> HostControlExecutionContract:
    return issue_execution_contract(
        operation=operation,
        lease_id=lease.id,
        lease_key=lease.key,
        project_id=machine.project_id,
        project=machine.project,
        settings=machine.settings,
        selection_reason=selection_reason,
        checks=list(checks),
        baselines=list(baselines),
        cases=list(cases),
        golden_destination=golden_destination,
        plan_execution_id=plan_execution_id,
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
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
    machine: str | None = None,
    select_any: bool = True,
) -> HostControlExecutionContract:
    """Validate settings and acquire the serial host claim."""
    if not str(session_id or "").strip():
        raise MachineQaProtocolError(
            "host-control execution requires an owning session"
        )
    try:
        admission = acquire_test_machine_admission(
            conn,
            project=project,
            session_id=session_id,
            machine=machine,
            select_any=select_any,
        )
    except CoordinationClaimStaleHolderError as exc:
        raise MachineQaProtocolError(str(exc)) from None
    except TestMachineFleetBusy as exc:
        held = exc.busy[0]
        raise MachineQaProtocolLeaseHeld(
            lease=held.lease,
            machine=held.machine,
            contention=held.contention,
        ) from None
    return _issue(
        admission.contract,
        admission.lease,
        operation=operation,
        checks=checks,
        baselines=baselines,
        cases=cases,
        golden_destination=golden_destination,
        selection_reason=admission.selection_reason,
        plan_execution_id=plan_execution_id,
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
            f"host-control lease {lease_id} was not issued"
        ) from exc
    machine_id = lease.target.machine_id
    if machine_id is None:
        raise MachineQaProtocolError("host-control lease does not name a machine")
    machine = load_test_machine_contract(
        conn,
        project=project,
        machine=machine_id,
    )
    resource_name = machine.settings["resource_name"]
    if lease.is_active and lease.key != host_claim_key(resource_name):
        raise MachineQaProtocolError(
            "host-control lease does not match the submitted target"
        )
    if lease.session_id != str(session_id or ""):
        raise MachineQaProtocolError(
            "host-control lease belongs to a different session"
        )
    expected_actor = str(lease.actor_id) if lease.actor_id is not None else None
    submitted_actor = str(actor_id) if actor_id is not None else None
    if expected_actor != submitted_actor:
        raise MachineQaProtocolError("host-control lease belongs to a different actor")
    if not lease.is_active and not allow_released:
        raise MachineQaProtocolError(
            f"host-control lease {lease.id} is no longer active"
        )
    return lease, machine


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
    roster_digest: str | None = None,
    ordinal: int | None = None,
    case_position: int | None = None,
    baseline_position: int | None = None,
) -> tuple[CoordinationClaim, HostControlExecutionContract]:
    """Lock the lease and validate actor, target, and issued contract."""
    lease, machine = _validate_lease_owner(
        conn,
        project=project,
        session_id=session_id,
        actor_id=actor_id,
        lease_id=lease_id,
        allow_released=allow_recorded_replay,
    )
    expected = _issue(
        machine,
        lease,
        operation=operation,
        checks=checks,
        baselines=baselines,
        cases=cases,
        golden_destination=golden_destination,
        plan_execution_id=plan_execution_id,
        roster_digest=roster_digest,
        ordinal=ordinal,
        case_position=case_position,
        baseline_position=baseline_position,
    )
    if lease.is_active and not hmac.compare_digest(
        expected.contract_digest,
        str(contract_digest),
    ):
        raise MachineQaProtocolError(
            "host-control target changed after execution began"
        )
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
