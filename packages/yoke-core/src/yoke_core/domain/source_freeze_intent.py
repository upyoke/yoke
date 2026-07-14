"""Compact cross-service source-freeze intent contract."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any


FREEZE_INTENT_SCHEMA = "yoke.source-freeze/v1"


def freeze_intent(
    *, database: dict[str, Any], frozen_at: str,
    authority: dict[str, Any], archive: dict[str, Any],
) -> dict[str, Any]:
    """Build the exact compact raw-JSON header and artifact contract."""
    events = authority.get("tables", {}).get("events", {})
    updated_values = [
        str(receipt["max_updated_at"])
        for receipt in authority.get("tables", {}).values()
        if receipt.get("max_updated_at") is not None
    ]
    strategy_sha = _sha256_text(json.dumps(
        authority.get("strategy_rows", []), sort_keys=True, separators=(",", ":"),
    ))
    body: dict[str, Any] = {
        "schema": FREEZE_INTENT_SCHEMA,
        # This is the frozen SOURCE identity, never the target CAS identity.
        "database": {
            "name": str(database["database"]),
            "oid": int(database["database_oid"]),
            "org": str(database["org"]),
        },
        "frozen_at": frozen_at,
        "authority_digest": str(authority["receipt_digest"]),
        "project_capabilities": authority["project_capabilities"],
        "capability_secrets": authority["capability_secrets"],
        "event_watermark": {
            "count": int(events.get("count", 0)),
            "max_id": (
                int(events["max_id"]) if events.get("max_id") is not None else None
            ),
            "max_created_at": authority.get("event_max_created_at"),
        },
        "updated_at_watermark": max(updated_values) if updated_values else None,
        "strategy_sha256": strategy_sha,
        "archive": {
            "sha256": str(archive["sha256"]),
            "bytes": int(archive["bytes"]),
            "catalog_digest": str(archive["catalog_digest"]),
        },
        "zero_writable_app_sessions": True,
    }
    body["receipt_id"] = _sha256_text(
        json.dumps(body, sort_keys=True, separators=(",", ":"))
    )
    return {"schema": body.pop("schema"), "receipt_id": body.pop("receipt_id"), **body}


def write_owner_only_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write a secret-free receipt with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "FREEZE_INTENT_SCHEMA", "file_sha256", "freeze_intent",
    "write_owner_only_json",
]
