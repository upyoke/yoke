"""Product archive validation and disposable round-trip receipts.

Both checks operate on the one-file portable universe archive
(:mod:`yoke_core.domain.universe_archive`): the enclosed freeze receipt
is verified against the enclosed dump payload first — the machine
derives every checksum from the artifact itself — and the dump is then
inspected (or restored) exactly as an import would."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_core.domain import db_backend, universe_archive, universe_portability
from yoke_core.domain.schema_fingerprint import fingerprint_portable_postgres_schema
from yoke_core.domain.schema_readiness import missing_readiness_tables
from yoke_core.domain.source_authority_cutover import authority_receipt


class ArchiveValidationError(RuntimeError):
    """A universe archive failed product validation."""


def inspect_archive(archive: Path | str) -> dict[str, object]:
    """Run bounded format/receipt/catalog checks without a database."""
    selected = Path(archive)
    with universe_archive.unpacked_universe_archive(
        selected,
        max_dump_bytes=universe_portability.DEFAULT_MAX_ARCHIVE_BYTES,
    ) as (dump, receipt):
        universe_archive.verify_receipt_binds_dump(receipt, dump)
        inspection = universe_portability.inspect_archive(dump)
        return _archive_receipt(selected, inspection, receipt)


def validate_archive_roundtrip(
    archive: Path | str,
    validation_dsn: str,
) -> dict[str, object]:
    """Restore into an explicitly disposable DB and emit safe receipts.

    The disposable database is replaced by the restore, exactly like a
    real import destination.
    """
    selected_dsn = str(validation_dsn or "").strip()
    if not selected_dsn:
        raise ArchiveValidationError("a disposable validation DSN is required")
    selected = Path(archive)
    with universe_archive.unpacked_universe_archive(
        selected,
        max_dump_bytes=universe_portability.DEFAULT_MAX_ARCHIVE_BYTES,
    ) as (dump, receipt):
        universe_archive.verify_receipt_binds_dump(receipt, dump)
        inspection = universe_portability.restore_universe(dump, selected_dsn)
        base_receipt = _archive_receipt(selected, inspection, receipt)
    conn = db_backend.connect_psycopg(selected_dsn)
    try:
        organizations = [
            str(row[0])
            for row in conn.execute(
                "SELECT slug FROM organizations ORDER BY id"
            ).fetchall()
        ]
        if len(organizations) != 1:
            raise ArchiveValidationError(
                "restored universe must contain exactly one organization"
            )
        missing = missing_readiness_tables(conn)
        if missing:
            raise ArchiveValidationError(
                "restored universe is missing readiness tables: "
                + ", ".join(missing)
            )
        projects = [
            {"id": int(row[0]), "slug": str(row[1])}
            for row in conn.execute(
                "SELECT id, slug FROM projects ORDER BY id"
            ).fetchall()
        ]
        fingerprint = fingerprint_portable_postgres_schema(conn)
        content_counts = universe_portability.user_content_counts(conn)
        restored_authority = authority_receipt(
            conn, include_content_digests=True,
        )
    finally:
        conn.close()
    return {
        **base_receipt,
        "roundtrip": True,
        "organization": organizations[0],
        "projects": projects,
        "schema_fingerprint": fingerprint,
        "content_counts": content_counts,
        "authority": restored_authority,
    }


def _archive_receipt(
    artifact: Path,
    inspection: universe_portability.ArchiveInspection,
    receipt: dict[str, Any],
) -> dict[str, object]:
    intent = receipt.get("freeze_intent") or {}
    return {
        "ok": True,
        "archive": str(artifact.resolve()),
        "bytes": int(artifact.stat().st_size),
        "dumped_from_postgres": str(inspection.dumped_from_postgres),
        "dumped_by_pg_dump": str(inspection.dumped_by_pg_dump),
        "table_entries": int(inspection.table_entries),
        "sha256": str(inspection.archive_sha256),
        "catalog": universe_portability.archive_catalog_receipt(inspection),
        "receipt_verified": True,
        "receipt": {
            "receipt_id": str(intent.get("receipt_id") or ""),
            "org": str((intent.get("database") or {}).get("org") or ""),
            "frozen_at": str(intent.get("frozen_at") or ""),
        },
    }


__all__ = [
    "ArchiveValidationError",
    "inspect_archive",
    "validate_archive_roundtrip",
]
