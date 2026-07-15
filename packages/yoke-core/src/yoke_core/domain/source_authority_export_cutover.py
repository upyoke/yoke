"""One-snapshot universe export through the rotated cutover credential."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import universe_export, universe_portability
from yoke_core.domain.source_authority_export_artifacts import (
    SourceExportArtifactError,
    cleanup_staged,
    prepare_artifact_set,
    publish_artifact_set,
)
from yoke_core.domain.source_authority_receipts import authority_receipt
from yoke_core.domain.source_freeze_intent import (
    file_sha256,
    freeze_intent,
)


def export_quiesced(
    *, out: str | Path, credential_file: str | Path,
    dsn: Optional[str] = None,
) -> dict[str, Any]:
    from yoke_core.domain import source_authority_cutover as cutover

    bundle = cutover._load_bundle(credential_file, original_dsn=dsn)
    resolved = bundle.cutover_dsn
    artifact_set = None
    try:
        conn = cutover._admin_connection(resolved)
        try:
            conn.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            fence = cutover.connect_fence.connect_fence_status(conn)
            if not fence["active"]:
                raise cutover.SourceAuthorityCutoverError(
                    "prod-admin universe export requires an active quiesce boundary"
                )
            state = cutover._validate_bundle_authority(conn, bundle)
            database = cutover._database_identity(conn)
            artifact_set = prepare_artifact_set(
                out, org_slug=database["org"],
            )
            frozen_at = state["frozen_at"]
            snapshot_id = str(
                conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
            )
            before = authority_receipt(conn)
            report = universe_export.export_universe(
                out=artifact_set.staged, dsn=resolved, snapshot=snapshot_id,
                org_slug=database["org"],
            )
            inspection = universe_portability.inspect_archive(report["artifact"])
            fence_after_dump = cutover.connect_fence.connect_fence_status(conn)
            if not fence_after_dump["active"]:
                raise cutover.SourceAuthorityCutoverError(
                    "source CONNECT fence changed during universe export"
                )
            after_compact = authority_receipt(conn)
            snapshot_receipt = authority_receipt(
                conn, include_content_digests=True,
            )
        finally:
            conn.close()
        if before["receipt_digest"] != after_compact["receipt_digest"]:
            raise cutover.SourceAuthorityCutoverError(
                "source authority changed during quiesced universe export"
            )
        catalog = universe_portability.archive_catalog_receipt(inspection)
        archive_sha = file_sha256(artifact_set.staged)
        if str(catalog["archive_sha256"]) != archive_sha:
            raise cutover.SourceAuthorityCutoverError(
                "archive checksum changed between validation and receipt binding"
            )
        proof_conn = cutover._admin_connection(resolved)
        try:
            proof_conn.execute(
                "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
            cutover._validate_bundle_authority(proof_conn, bundle)
            final_fence = cutover.connect_fence.connect_fence_status(proof_conn)
            fresh_receipt = authority_receipt(
                proof_conn, include_content_digests=True,
            )
            fence_after_receipt = cutover.connect_fence.connect_fence_status(
                proof_conn
            )
        finally:
            proof_conn.close()
        if not final_fence["active"] or not fence_after_receipt["active"]:
            raise cutover.SourceAuthorityCutoverError(
                "source CONNECT fence was not durable after snapshot export"
            )
        if snapshot_receipt != fresh_receipt:
            raise cutover.SourceAuthorityCutoverError(
                "source authority changed after the exported snapshot"
            )
        intent = freeze_intent(
            database=database, frozen_at=frozen_at, authority=fresh_receipt,
            archive={
                "sha256": archive_sha,
                "bytes": int(report["bytes"]),
                "catalog_digest": str(catalog["catalog_digest"]),
            },
        )
        receipt = {
            "freeze_intent": intent,
            "source_authority": fresh_receipt,
            "catalog": catalog,
        }
        publish_artifact_set(
            artifact_set, intent=intent, receipt=receipt,
        )
        return {
            **report,
            "artifact": str(artifact_set.final),
            "sha256": intent["archive"]["sha256"],
            "catalog": catalog,
            "source_authority": fresh_receipt,
            "stable_watermarks": True,
            "snapshot_proof": {
                "isolation": "repeatable-read-read-only",
                "snapshot_id_sha256": hashlib.sha256(
                    snapshot_id.encode("utf-8")
                ).hexdigest(),
                "compact_before_digest": before["receipt_digest"],
                "compact_after_digest": after_compact["receipt_digest"],
                "fresh_after_dump_digest": fresh_receipt["receipt_digest"],
                "connect_fence": fence_after_receipt,
            },
            "freeze_intent": intent,
            "freeze_intent_header": json.dumps(
                intent, sort_keys=True, separators=(",", ":"),
            ),
            "freeze_intent_path": str(artifact_set.final_intent),
            "receipt_sidecar_path": str(artifact_set.final_receipt),
        }
    except cutover.connect_fence.SourceConnectFenceError as exc:
        raise cutover.SourceAuthorityCutoverError(str(exc)) from exc
    except SourceExportArtifactError as exc:
        raise cutover.SourceAuthorityCutoverError(str(exc)) from exc
    finally:
        if artifact_set is not None:
            cleanup_staged(artifact_set)


__all__ = ["export_quiesced"]
