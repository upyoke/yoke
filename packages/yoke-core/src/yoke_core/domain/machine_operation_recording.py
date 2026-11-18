"""Authority-side persistence of one machine's last receipt per operation."""

from __future__ import annotations

import hmac
import json
from typing import Any, Mapping, Sequence

from yoke_contracts.machine_qa_execution import (
    HostControlExecutionContract,
    RESET_OPERATION,
)

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_contracts.timestamps import utc_now, parse_instant
from yoke_core.domain.test_machine_rows import test_machine_id


#: The operations whose receipts live beside the verification row rather than
#: in it. Verification decides readiness; these record what was last done.
from yoke_contracts.machine_qa_host_control import RECORDED_TEST_MACHINE_OPERATIONS

RECORDED_OPERATIONS = RECORDED_TEST_MACHINE_OPERATIONS


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_result(row: Any) -> dict[str, Any]:
    receipt = json.loads(str(row["receipt_json"] or "{}"))
    return {
        "operation": str(row["operation"]),
        "status": str(row["status"]),
        "performed_at": parse_instant(row["performed_at"]),
        "checks": list(receipt.get("checks") or []),
        "error_code": row["error_code"],
    }


def record_test_machine_operation(
    conn: Any,
    *,
    test_machine: str,
    operation: str,
    status: str,
    checks: Sequence[Mapping[str, Any]],
    error_code: str | None,
    lease_id: int,
    contract_digest: str,
    commit: bool = True,
) -> dict[str, Any]:
    """Persist one server-accepted, secret-free operation receipt."""
    if operation not in RECORDED_OPERATIONS:
        raise ValueError(f"{operation!r} does not record an operation receipt")
    marker = _marker(conn)
    machine_id = test_machine_id(conn, test_machine)
    now = utc_now()
    receipt = json.dumps(
        {"checks": list(checks)},
        separators=(",", ":"),
        sort_keys=True,
    )
    conn.execute(
        "INSERT INTO test_machine_operation_receipts("
        "test_machine_id,operation,status,performed_at,receipt_json,"
        f"error_code,lease_id,contract_digest,updated_at) VALUES("
        f"{','.join([marker] * 9)}) "
        "ON CONFLICT(test_machine_id,operation) DO UPDATE SET "
        "status=EXCLUDED.status, performed_at=EXCLUDED.performed_at, "
        "receipt_json=EXCLUDED.receipt_json, error_code=EXCLUDED.error_code, "
        "lease_id=EXCLUDED.lease_id, contract_digest=EXCLUDED.contract_digest, "
        "updated_at=EXCLUDED.updated_at",
        (
            machine_id,
            operation,
            status,
            instant_parameter(conn, now),
            receipt,
            error_code,
            int(lease_id),
            str(contract_digest),
            instant_parameter(conn, now),
        ),
    )
    if commit:
        conn.commit()
    return {
        "operation": operation,
        "status": status,
        "performed_at": now,
        "checks": list(checks),
        "error_code": error_code,
    }


def record_test_machine_baseline_reset(
    conn: Any,
    contract: HostControlExecutionContract,
    preparation: Mapping[str, Any],
    *,
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any] | None:
    """Record a plan preparation reset when its contract authorized one."""
    if not contract.baselines:
        return None
    baseline = contract.baselines[0]
    ok = bool(preparation.get("ok"))
    evidence = dict(preparation.get("evidence") or {})
    return record_test_machine_operation(
        conn,
        test_machine=contract.settings["resource_name"],
        operation=RESET_OPERATION,
        status="verified" if ok else "error",
        checks=[{**evidence, "name": baseline, "ok": ok}],
        error_code=str(preparation.get("error_code") or "") or None,
        lease_id=lease_id,
        contract_digest=contract_digest,
    )


def recorded_test_machine_operation(
    conn: Any,
    *,
    test_machine: str,
    operation: str,
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any] | None:
    """Return the canonical receipt for an already-accepted submission.

    A submission whose lease was released before its reply arrived is replayed
    rather than refused: the work happened on the host either way, and a
    refusal would tell an operator the opposite.
    """
    marker = _marker(conn)
    row = conn.execute(
        "SELECT operation,status,performed_at,receipt_json,error_code,"
        "lease_id,contract_digest FROM test_machine_operation_receipts "
        f"WHERE test_machine_id=(SELECT id FROM test_machines WHERE name={marker}) "
        f"AND operation={marker}",
        (test_machine, operation),
    ).fetchone()
    if row is None:
        return None
    stored_digest = row["contract_digest"]
    if (
        row["lease_id"] is None
        or int(row["lease_id"]) != int(lease_id)
        or not isinstance(stored_digest, str)
        or not hmac.compare_digest(stored_digest, str(contract_digest))
    ):
        return None
    return _row_result(row)


def test_machine_operation_receipts(
    conn: Any,
    machine_id: int,
) -> list[dict[str, Any]]:
    """Return every recorded operation receipt for one machine, newest first."""
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT operation,status,performed_at,receipt_json,error_code "
        "FROM test_machine_operation_receipts "
        f"WHERE test_machine_id={marker} "
        "ORDER BY performed_at DESC, operation",
        (machine_id,),
    ).fetchall()
    return [_row_result(row) for row in rows]


__all__ = [
    "RECORDED_OPERATIONS",
    "record_test_machine_baseline_reset",
    "record_test_machine_operation",
    "recorded_test_machine_operation",
    "test_machine_operation_receipts",
]
