"""Authority-side persistence of Test Machine verification receipts."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import instant_parameter
from yoke_contracts.timestamps import utc_now, parse_instant, format_instant
from yoke_core.domain.machine_qa_execution_protocol import (
    HOST_CONTROL_SUBMISSION_RECEIPT_KEY,
    host_control_submission_receipt,
    host_control_submission_receipt_matches,
)
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
from yoke_contracts.machine_config.test_machine import test_machine_capability_type

_SUBMISSION_HISTORY_KEY = "host_control_submission_history"


def record_test_machine_verification(
    conn: Any,
    project_id: int,
    *,
    machine: str,
    status: str,
    checks: Sequence[Mapping[str, Any]],
    error_code: str | None,
    lease_id: int | None = None,
    contract_digest: str | None = None,
) -> dict[str, Any]:
    """Persist one server-accepted, secret-free verification receipt."""
    if (lease_id is None) != (contract_digest is None):
        raise ValueError(
            "verification submission identity requires lease and contract digest"
        )
    ensure_test_machine_schema(conn)
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    capability_type = test_machine_capability_type(machine)
    now = utc_now()
    previous = conn.execute(
        "SELECT status,checked_at,receipt_json,error_code "
        "FROM test_machine_verifications "
        f"WHERE project_id={marker} AND capability_type={marker}",
        (int(project_id), capability_type),
    ).fetchone()
    previous_receipt = (
        _json_object(previous["receipt_json"]) if previous is not None else {}
    )
    history = [
        dict(entry)
        for entry in previous_receipt.get(_SUBMISSION_HISTORY_KEY, [])
        if isinstance(entry, Mapping)
    ]
    previous_identity = previous_receipt.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY)
    if previous is not None and isinstance(previous_identity, Mapping):
        history.append(
            {
                HOST_CONTROL_SUBMISSION_RECEIPT_KEY: dict(previous_identity),
                "status": str(previous["status"]),
                "checked_at": (
                    format_instant(previous["checked_at"])
                    if previous["checked_at"] is not None
                    else None
                ),
                "checks": list(previous_receipt.get("checks") or []),
                "error_code": previous["error_code"],
            }
        )
    receipt_payload: dict[str, Any] = {"checks": list(checks)}
    if history:
        receipt_payload[_SUBMISSION_HISTORY_KEY] = history
    if lease_id is not None and contract_digest is not None:
        receipt_payload[HOST_CONTROL_SUBMISSION_RECEIPT_KEY] = (
            host_control_submission_receipt(lease_id, contract_digest)
        )
    receipt = json.dumps(
        receipt_payload,
        separators=(",", ":"),
        sort_keys=True,
    )
    conn.execute(
        "INSERT INTO test_machine_verifications("
        "project_id,capability_type,status,checked_at,receipt_json,error_code,updated_at"
        f") VALUES({marker},{marker},{marker},{marker},{marker},{marker},{marker}) "
        "ON CONFLICT(project_id,capability_type) DO UPDATE SET "
        "status=EXCLUDED.status, checked_at=EXCLUDED.checked_at, "
        "receipt_json=EXCLUDED.receipt_json, error_code=EXCLUDED.error_code, "
        "updated_at=EXCLUDED.updated_at",
        (
            project_id,
            capability_type,
            status,
            instant_parameter(conn, now),
            receipt,
            error_code,
            instant_parameter(conn, now),
        ),
    )
    conn.execute(
        "UPDATE project_capabilities SET verified_at="
        f"{marker} WHERE project_id={marker} AND type={marker}",
        (
            instant_parameter(conn, now) if status == "verified" else None,
            project_id,
            capability_type,
        ),
    )
    conn.commit()
    return {
        "status": status,
        "checked_at": now,
        "checks": list(checks),
        "error_code": error_code,
    }


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, Mapping) else {}


def recorded_test_machine_verification(
    conn: Any,
    project_id: int,
    *,
    machine: str,
    lease_id: int,
    contract_digest: str,
) -> dict[str, Any] | None:
    """Return the canonical verification for an issued submission."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    capability_type = test_machine_capability_type(machine)
    row = conn.execute(
        "SELECT status,checked_at,receipt_json,error_code "
        "FROM test_machine_verifications "
        f"WHERE project_id={marker} AND capability_type={marker}",
        (int(project_id), capability_type),
    ).fetchone()
    if row is None:
        return None
    receipt = _json_object(row["receipt_json"])
    if not host_control_submission_receipt_matches(
        receipt.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY),
        lease_id=lease_id,
        contract_digest=contract_digest,
    ):
        for recorded in receipt.get(_SUBMISSION_HISTORY_KEY, []):
            if not isinstance(recorded, Mapping):
                continue
            if host_control_submission_receipt_matches(
                recorded.get(HOST_CONTROL_SUBMISSION_RECEIPT_KEY),
                lease_id=lease_id,
                contract_digest=contract_digest,
            ):
                return {
                    "status": str(recorded["status"]),
                    "checked_at": (
                        parse_instant(recorded["checked_at"])
                        if recorded["checked_at"] is not None
                        else None
                    ),
                    "checks": list(recorded.get("checks") or []),
                    "error_code": recorded.get("error_code"),
                }
        return None
    return {
        "status": str(row["status"]),
        "checked_at": (
            parse_instant(row["checked_at"]) if row["checked_at"] is not None else None
        ),
        "checks": list(receipt.get("checks") or []),
        "error_code": row["error_code"],
    }


__all__ = [
    "record_test_machine_verification",
    "recorded_test_machine_verification",
]
