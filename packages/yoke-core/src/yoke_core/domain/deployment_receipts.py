"""Canonical digest and read operations for archived deployment receipts."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Mapping, Optional

from yoke_core.domain.db_helpers import connect, query_one, query_rows
from yoke_core.domain.deployment_receipt_schema import (
    FLOW_RECEIPT_SCHEMA,
    RUN_RECEIPT_SCHEMA,
)


FLOW_LIST_FIELDS = (
    "flow_id", "project_id_snapshot", "project_slug_snapshot",
    "definition_observed_at", "receipt_schema", "payload_sha256",
    "archived_at",
)
RUN_LIST_FIELDS = (
    "run_id", "project_id_snapshot", "project_slug_snapshot", "flow_id",
    "target_env", "status", "run_created_at", "receipt_schema",
    "payload_sha256", "archived_at",
)


class DeploymentReceiptIntegrityError(ValueError):
    """A stored receipt payload is malformed or does not match its digest."""


def canonical_receipt_payload(payload: Mapping[str, Any]) -> str:
    """Return the stable UTF-8 JSON text used for receipt hashing/storage."""
    if not isinstance(payload, Mapping):
        raise DeploymentReceiptIntegrityError(
            "deployment receipt payload must be a JSON object"
        )
    try:
        return json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DeploymentReceiptIntegrityError(
            f"deployment receipt payload is not canonical JSON: {exc}"
        ) from exc


def deployment_receipt_digest(payload: Mapping[str, Any]) -> str:
    """Return the SHA-256 digest of a canonical receipt payload."""
    canonical = canonical_receipt_payload(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def receipt_storage_values(payload: Mapping[str, Any]) -> tuple[str, str]:
    """Return canonical JSON text and its matching SHA-256 digest."""
    canonical = canonical_receipt_payload(payload)
    return canonical, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_deployment_receipt(
    stored_payload: str,
    expected_digest: str,
) -> dict[str, Any]:
    """Parse a stored receipt and reject malformed or digest-mismatched data."""
    try:
        payload = json.loads(stored_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DeploymentReceiptIntegrityError(
            "stored deployment receipt payload is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise DeploymentReceiptIntegrityError(
            "stored deployment receipt payload must be a JSON object"
        )
    actual = deployment_receipt_digest(payload)
    expected = str(expected_digest or "").lower()
    if len(expected) != 64 or not hmac.compare_digest(actual, expected):
        raise DeploymentReceiptIntegrityError(
            "stored deployment receipt payload digest does not match"
        )
    return payload


def _verified_row(row: Any, expected_schema: str) -> dict[str, Any]:
    data = dict(row)
    if data.get("receipt_schema") != expected_schema:
        raise DeploymentReceiptIntegrityError(
            "stored deployment receipt schema is not supported"
        )
    data["payload"] = verify_deployment_receipt(
        str(data["payload"]), str(data["payload_sha256"])
    )
    data["digest_verified"] = True
    return data


def get_flow_receipt(
    flow_id: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return one verified archived flow definition, or ``None``."""
    conn = connect(db_path)
    try:
        row = query_one(
            conn,
            "SELECT flow_id, project_id_snapshot, project_slug_snapshot, "
            "definition_observed_at, receipt_schema, payload, "
            "payload_sha256, archived_at FROM deployment_flow_receipts "
            "WHERE flow_id=%s",
            (flow_id,),
        )
        return None if row is None else _verified_row(row, FLOW_RECEIPT_SCHEMA)
    finally:
        conn.close()


def list_flow_receipts(
    *,
    project: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List verified archived flow definitions by stable summary fields."""
    conn = connect(db_path)
    try:
        where = ""
        params: tuple[object, ...] = ()
        if project is not None:
            where = "WHERE project_slug_snapshot=%s"
            params = (project,)
        rows = query_rows(
            conn,
            "SELECT flow_id, project_id_snapshot, project_slug_snapshot, "
            "definition_observed_at, receipt_schema, payload, "
            "payload_sha256, archived_at FROM deployment_flow_receipts "
            f"{where} ORDER BY definition_observed_at, flow_id",
            params,
        )
        return [
            {field: verified[field] for field in FLOW_LIST_FIELDS}
            for verified in (
                _verified_row(row, FLOW_RECEIPT_SCHEMA) for row in rows
            )
        ]
    finally:
        conn.close()


def get_run_receipt(
    run_id: str,
    *,
    db_path: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Return one verified archived deployment run graph, or ``None``."""
    conn = connect(db_path)
    try:
        row = query_one(
            conn,
            "SELECT run_id, project_id_snapshot, project_slug_snapshot, "
            "flow_id, target_env, status, run_created_at, receipt_schema, "
            "payload, payload_sha256, archived_at "
            "FROM deployment_run_receipts WHERE run_id=%s",
            (run_id,),
        )
        return None if row is None else _verified_row(row, RUN_RECEIPT_SCHEMA)
    finally:
        conn.close()


def list_run_receipts(
    *,
    project: Optional[str] = None,
    flow: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> list[dict[str, Any]]:
    """List verified archived run summaries with optional exact filters."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("project_slug_snapshot", project),
        ("flow_id", flow),
        ("status", status),
    ):
        if value is not None:
            clauses.append(f"{column}=%s")
            params.append(value)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    conn = connect(db_path)
    try:
        rows = query_rows(
            conn,
            "SELECT run_id, project_id_snapshot, project_slug_snapshot, "
            "flow_id, target_env, status, run_created_at, receipt_schema, "
            "payload, payload_sha256, archived_at "
            f"FROM deployment_run_receipts {where} "
            "ORDER BY run_created_at, run_id",
            tuple(params),
        )
        return [
            {field: verified[field] for field in RUN_LIST_FIELDS}
            for verified in (
                _verified_row(row, RUN_RECEIPT_SCHEMA) for row in rows
            )
        ]
    finally:
        conn.close()


__all__ = [
    "DeploymentReceiptIntegrityError",
    "FLOW_LIST_FIELDS",
    "FLOW_RECEIPT_SCHEMA",
    "RUN_LIST_FIELDS",
    "RUN_RECEIPT_SCHEMA",
    "canonical_receipt_payload",
    "deployment_receipt_digest",
    "get_flow_receipt",
    "get_run_receipt",
    "list_flow_receipts",
    "list_run_receipts",
    "receipt_storage_values",
    "verify_deployment_receipt",
]
