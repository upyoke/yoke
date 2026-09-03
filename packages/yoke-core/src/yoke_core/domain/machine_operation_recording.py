"""Authority-side persistence of one machine's last receipt per operation."""

from __future__ import annotations

import hmac
import json
from typing import Any, Mapping, Sequence

from yoke_contracts.machine_config.test_machine import test_machine_capability_type
from yoke_contracts.machine_qa_execution import (
    BRIDGE_DIAGNOSE_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    RESET_OPERATION,
)

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema


#: The operations whose receipts live beside the verification row rather than
#: in it. Verification decides readiness; these record what was last done.
RECORDED_OPERATIONS = (
    RESET_OPERATION,
    GOLDEN_CAPTURE_OPERATION,
    BRIDGE_DIAGNOSE_OPERATION,
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _row_result(row: Any) -> dict[str, Any]:
    receipt = json.loads(str(row["receipt_json"] or "{}"))
    return {
        "operation": str(row["operation"]),
        "status": str(row["status"]),
        "performed_at": str(row["performed_at"]),
        "checks": list(receipt.get("checks") or []),
        "error_code": row["error_code"],
    }


def record_test_machine_operation(
    conn: Any,
    project_id: int,
    *,
    machine: str,
    operation: str,
    status: str,
    checks: Sequence[Mapping[str, Any]],
    error_code: str | None,
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any]:
    """Persist one server-accepted, secret-free operation receipt."""
    if operation not in RECORDED_OPERATIONS:
        raise ValueError(f"{operation!r} does not record an operation receipt")
    ensure_test_machine_schema(conn)
    marker = _marker(conn)
    capability_type = test_machine_capability_type(machine)
    now = iso8601_now()
    receipt = json.dumps(
        {"checks": list(checks)},
        separators=(",", ":"),
        sort_keys=True,
    )
    conn.execute(
        "INSERT INTO test_machine_operation_receipts("
        "project_id,capability_type,operation,status,performed_at,receipt_json,"
        f"error_code,lease_id,contract_digest,updated_at) VALUES("
        f"{','.join([marker] * 10)}) "
        "ON CONFLICT(project_id,capability_type,operation) DO UPDATE SET "
        "status=EXCLUDED.status, performed_at=EXCLUDED.performed_at, "
        "receipt_json=EXCLUDED.receipt_json, error_code=EXCLUDED.error_code, "
        "lease_id=EXCLUDED.lease_id, contract_digest=EXCLUDED.contract_digest, "
        "updated_at=EXCLUDED.updated_at",
        (
            int(project_id),
            capability_type,
            operation,
            status,
            now,
            receipt,
            error_code,
            int(lease_id),
            str(contract_digest),
            now,
        ),
    )
    conn.commit()
    return {
        "operation": operation,
        "status": status,
        "performed_at": now,
        "checks": list(checks),
        "error_code": error_code,
    }


def recorded_test_machine_operation(
    conn: Any,
    project_id: int,
    *,
    machine: str,
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
        f"WHERE project_id={marker} AND capability_type={marker} "
        f"AND operation={marker}",
        (int(project_id), test_machine_capability_type(machine), operation),
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
    project_id: int,
    *,
    capability_type: str,
) -> list[dict[str, Any]]:
    """Return every recorded operation receipt for one machine, newest first."""
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT operation,status,performed_at,receipt_json,error_code "
        "FROM test_machine_operation_receipts "
        f"WHERE project_id={marker} AND capability_type={marker} "
        "ORDER BY performed_at DESC, operation",
        (int(project_id), capability_type),
    ).fetchall()
    return [_row_result(row) for row in rows]


__all__ = [
    "RECORDED_OPERATIONS",
    "record_test_machine_operation",
    "recorded_test_machine_operation",
    "test_machine_operation_receipts",
]
