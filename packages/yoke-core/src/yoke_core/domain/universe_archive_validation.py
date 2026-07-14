"""Product archive validation and disposable round-trip receipts."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import db_backend, universe_portability
from yoke_core.domain.schema_fingerprint import fingerprint_portable_postgres_schema
from yoke_core.domain.schema_readiness import missing_readiness_tables
from yoke_core.domain.source_authority_cutover import authority_receipt


class ArchiveValidationError(RuntimeError):
    """A universe archive failed product validation."""


def inspect_archive(archive: Path | str) -> dict[str, object]:
    """Run bounded format/catalog checks without requiring a database."""
    selected = Path(archive)
    inspection = universe_portability.inspect_archive(selected)
    return _inspection_receipt(inspection)


def validate_archive_roundtrip(
    archive: Path | str,
    validation_dsn: str,
) -> dict[str, object]:
    """Restore into an explicitly disposable DB and emit safe receipts."""
    selected_dsn = str(validation_dsn or "").strip()
    if not selected_dsn:
        raise ArchiveValidationError("a disposable validation DSN is required")
    selected = Path(archive)
    inspection = universe_portability.restore_universe(selected, selected_dsn)
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
        **_inspection_receipt(inspection),
        "roundtrip": True,
        "organization": organizations[0],
        "projects": projects,
        "schema_fingerprint": fingerprint,
        "content_counts": content_counts,
        "authority": restored_authority,
    }


def _inspection_receipt(
    inspection: universe_portability.ArchiveInspection,
) -> dict[str, object]:
    return {
        "ok": True,
        "archive": str(Path(inspection.path).resolve()),
        "bytes": int(inspection.size_bytes),
        "dumped_from_postgres": str(inspection.dumped_from_postgres),
        "dumped_by_pg_dump": str(inspection.dumped_by_pg_dump),
        "table_entries": int(inspection.table_entries),
        "sha256": str(inspection.archive_sha256),
        "catalog": universe_portability.archive_catalog_receipt(inspection),
    }


__all__ = [
    "ArchiveValidationError",
    "inspect_archive",
    "validate_archive_roundtrip",
]
