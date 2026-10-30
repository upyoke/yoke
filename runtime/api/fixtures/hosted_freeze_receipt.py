"""Hosted source-freeze receipt admission fixture copied from Platform.

Keep the consumer's data checks explicit, including its archive-key boundary.
The artifact manifest contract is checked separately until the consumer lands it.
"""

import hashlib
import json
import re
from typing import Any

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def assert_hosted_receipt(intent):
    receipt = intent.source_freeze_receipt
    required = {
        "schema",
        "receipt_id",
        "database",
        "frozen_at",
        "authority_digest",
        "project_capabilities",
        "capability_secrets",
        "updated_at_watermark",
        "strategy_sha256",
        "archive",
        "zero_writable_app_sessions",
    }
    if set(receipt) != required:
        raise ValueError("complete source freeze receipt is required")
    database = receipt.get("database")
    archive = receipt.get("archive")
    project_capabilities = receipt.get("project_capabilities")
    capability_secrets = receipt.get("capability_secrets")
    try:
        database_oid = (
            int(database.get("oid", -1)) if isinstance(database, dict) else -1
        )
        archive_bytes = int(archive.get("bytes", 0)) if isinstance(archive, dict) else 0
    except (TypeError, ValueError):
        database_oid = -1
        archive_bytes = 0
    freeze_body = dict(receipt)
    freeze_receipt_id = freeze_body.pop("receipt_id", None)
    if (
        receipt.get("schema") != "yoke.source-freeze/v2"
        or freeze_receipt_id != _digest(freeze_body)
        or not _SHA256.fullmatch(str(receipt.get("authority_digest", "")))
        or not _SHA256.fullmatch(str(receipt.get("strategy_sha256", "")))
        or not isinstance(receipt.get("frozen_at"), str)
        or not receipt["frozen_at"].strip()
        or not (
            receipt.get("updated_at_watermark") is None
            or isinstance(receipt.get("updated_at_watermark"), str)
        )
        or not isinstance(database, dict)
        or set(database) != {"name", "oid", "org"}
        or database_oid <= 0
        or not str(database.get("name", "")).strip()
        # The receipt describes the source authority. Its organization name is
        # content-bound evidence, not the destination Platform organization.
        # Cross-authority migrations legitimately map those separate identities.
        or not str(database.get("org", "")).strip()
        or not isinstance(archive, dict)
        or set(archive) != {"sha256", "bytes", "catalog_digest"}
        or archive.get("sha256") != intent.archive_sha256
        or archive_bytes <= 0
        or not _SHA256.fullmatch(str(archive.get("catalog_digest", "")))
        or not _valid_typed_receipt(
            project_capabilities, "yoke.project-capabilities/v1"
        )
        or not _valid_typed_receipt(capability_secrets, "yoke.capability-secrets/v1")
        or not set(capability_secrets["types"]).issubset(
            intent.environment_capability_types
        )
        or receipt.get("zero_writable_app_sessions") is not True
    ):
        raise ValueError("source freeze intent is invalid")


def _valid_typed_receipt(value: Any, schema: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"schema", "sha256", "types"}:
        return False
    types = value.get("types")
    return (
        value.get("schema") == schema
        and isinstance(types, dict)
        and value.get("sha256") == _digest(types)
    )
