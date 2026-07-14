"""One-snapshot universe export through the rotated cutover credential."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import universe_export, universe_portability
from yoke_core.domain.source_authority_receipts import authority_receipt
from yoke_core.domain.source_freeze_intent import (
    file_sha256,
    freeze_intent,
    write_owner_only_json,
)


def export_quiesced(
    *, out: str | Path, credential_file: str | Path,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    from yoke_core.domain import source_authority_cutover as cutover

    bundle = cutover._load_bundle(credential_file, original_dsn=dsn)
    resolved = bundle.cutover_dsn
    conn = cutover._admin_connection(resolved)
    try:
        conn.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        fence = cutover.connect_fence.connect_fence_status(conn)
        if not fence["active"]:
            raise cutover.SourceAuthorityCutoverError(
                "prod-admin universe export requires an active quiesce boundary"
            )
        state = cutover._validate_bundle_authority(conn, bundle)
        database = cutover._database_identity(conn)
        frozen_at = state["frozen_at"]
        snapshot_id = str(conn.execute("SELECT pg_export_snapshot()").fetchone()[0])
        before = authority_receipt(conn)
        report = universe_export.export_universe(
            out=out, dsn=resolved, snapshot=snapshot_id,
            org_slug=database["org"],
        )
        inspection = universe_portability.inspect_archive(report["artifact"])
        fence_after_dump = cutover.connect_fence.connect_fence_status(conn)
        if not fence_after_dump["active"]:
            raise cutover.SourceAuthorityCutoverError(
                "source CONNECT fence changed during universe export"
            )
        after_compact = authority_receipt(conn)
        after = authority_receipt(conn, include_content_digests=True)
    except cutover.connect_fence.SourceConnectFenceError as exc:
        raise cutover.SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        conn.close()
    if before["receipt_digest"] != after_compact["receipt_digest"]:
        raise cutover.SourceAuthorityCutoverError(
            "source authority changed during quiesced universe export"
        )
    catalog = universe_portability.archive_catalog_receipt(inspection)
    archive_sha = file_sha256(Path(report["artifact"]))
    if str(catalog["archive_sha256"]) != archive_sha:
        raise cutover.SourceAuthorityCutoverError(
            "archive checksum changed between validation and receipt binding"
        )
    proof_conn = cutover._admin_connection(resolved)
    try:
        cutover._validate_bundle_authority(proof_conn, bundle)
        final_fence = cutover.connect_fence.connect_fence_status(proof_conn)
    finally:
        proof_conn.close()
    if not final_fence["active"]:
        raise cutover.SourceAuthorityCutoverError(
            "source CONNECT fence was not durable after snapshot export"
        )
    intent = freeze_intent(
        database=database,
        frozen_at=frozen_at,
        authority=after,
        archive={
            "sha256": archive_sha,
            "bytes": int(report["bytes"]),
            "catalog_digest": str(catalog["catalog_digest"]),
        },
    )
    artifact = Path(report["artifact"])
    intent_path = artifact.with_suffix(artifact.suffix + ".source-freeze-intent.json")
    receipt_path = artifact.with_suffix(artifact.suffix + ".source-freeze-receipt.json")
    write_owner_only_json(intent_path, intent)
    write_owner_only_json(
        receipt_path,
        {"freeze_intent": intent, "source_authority": after, "catalog": catalog},
    )
    return {
        **report,
        "sha256": intent["archive"]["sha256"],
        "catalog": catalog,
        "source_authority": after,
        "stable_watermarks": True,
        "snapshot_proof": {
            "isolation": "repeatable-read-read-only",
            "snapshot_id_sha256": hashlib.sha256(
                snapshot_id.encode("utf-8")
            ).hexdigest(),
            "compact_before_digest": before["receipt_digest"],
            "compact_after_digest": after_compact["receipt_digest"],
            "connect_fence": final_fence,
        },
        "freeze_intent": intent,
        "freeze_intent_header": json.dumps(
            intent, sort_keys=True, separators=(",", ":"),
        ),
        "freeze_intent_path": str(intent_path),
        "receipt_sidecar_path": str(receipt_path),
    }


__all__ = ["export_quiesced"]
