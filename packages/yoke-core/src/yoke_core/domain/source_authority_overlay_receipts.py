"""Secret-free receipts for authority tables overlaid by the destination."""

from __future__ import annotations

import hashlib
import json
from typing import Any


PROJECT_CAPABILITIES_SCHEMA = "yoke.project-capabilities/v1"
CAPABILITY_SECRETS_SCHEMA = "yoke.capability-secrets/v1"


def project_capabilities_receipt(conn: object) -> dict[str, Any]:
    """Hash canonical capability state by type and project without settings."""
    query = (
        "SELECT project_id, type, settings, verified_at, created_at "
        "FROM project_capabilities ORDER BY type, project_id"
    )
    types: dict[str, dict[str, Any]] = {}
    for row in _batched_rows(conn, "source_project_capabilities", query):
        project_id = int(row[0])
        capability_type = str(row[1])
        canonical = {
            "project_id": project_id,
            "type": capability_type,
            "settings": _canonical_json_value(row[2]),
            "verified_at": None if row[3] is None else str(row[3]),
            "created_at": str(row[4]),
        }
        entry = types.setdefault(
            capability_type, {"count": 0, "projects": {}},
        )
        entry["count"] += 1
        entry["projects"][str(project_id)] = _digest(canonical)

    for entry in types.values():
        entry["sha256"] = _digest(entry["projects"])
    body: dict[str, Any] = {
        "schema": PROJECT_CAPABILITIES_SCHEMA,
        "types": types,
    }
    body["sha256"] = _digest(types)
    return body


def capability_secrets_receipt(conn: object) -> dict[str, Any]:
    """Hash secret rows by type/project without emitting keys or values."""
    query = (
        "SELECT project_id, type, key, value, source, created_at "
        "FROM capability_secrets ORDER BY type, project_id, key"
    )
    types: dict[str, dict[str, Any]] = {}
    current_key: tuple[str, str] | None = None
    current_count = 0
    current_digest: Any = None

    def finish_project() -> None:
        nonlocal current_key, current_count, current_digest
        if current_key is None:
            return
        current_digest.update(b"]")
        secret_type, project_id = current_key
        entry = types.setdefault(secret_type, {"count": 0, "projects": {}})
        entry["count"] += current_count
        entry["projects"][project_id] = {
            "count": current_count, "sha256": current_digest.hexdigest(),
        }

    for row in _batched_rows(conn, "source_capability_secrets", query):
        project_id = int(row[0])
        secret_type = str(row[1])
        row_key = (secret_type, str(project_id))
        if row_key != current_key:
            finish_project()
            current_key = row_key
            current_count = 0
            current_digest = hashlib.sha256()
            current_digest.update(b"[")
        canonical = {
            "project_id": project_id,
            "type": secret_type,
            "key": str(row[2]),
            "value": str(row[3]),
            "source": str(row[4]),
            "created_at": str(row[5]),
        }
        if current_count:
            current_digest.update(b",")
        current_digest.update(_canonical_bytes(canonical))
        current_count += 1
    finish_project()
    for entry in types.values():
        entry["sha256"] = _digest(entry["projects"])
    body: dict[str, Any] = {
        "schema": CAPABILITY_SECRETS_SCHEMA,
        "types": types,
    }
    body["sha256"] = _digest(types)
    return body


def filter_typed_receipt(
    receipt: dict[str, Any], included_types: set[str] | frozenset[str],
) -> dict[str, Any]:
    """Select named types and recompute the exact parent receipt digest."""
    types = {
        name: value
        for name, value in receipt.get("types", {}).items()
        if name in included_types
    }
    body = {"schema": str(receipt["schema"]), "types": types}
    body["sha256"] = _digest(types)
    return body


def _canonical_json_value(value: Any) -> Any:
    if value is None:
        return {}
    if isinstance(value, str):
        return json.loads(value)
    return value


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _batched_rows(conn: object, cursor_name: str, query: str):
    """Yield a server-side cursor in fixed batches inside the caller snapshot."""
    cursor = conn.cursor(name=cursor_name)
    try:
        cursor.execute(query)
        while True:
            rows = cursor.fetchmany(256)
            if not rows:
                return
            yield from rows
    finally:
        cursor.close()


__all__ = [
    "CAPABILITY_SECRETS_SCHEMA", "PROJECT_CAPABILITIES_SCHEMA",
    "capability_secrets_receipt", "filter_typed_receipt",
    "project_capabilities_receipt",
]
