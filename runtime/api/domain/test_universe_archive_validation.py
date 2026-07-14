from pathlib import Path
from unittest.mock import MagicMock

import pytest

from yoke_core.domain import universe_archive_validation as validator


def test_roundtrip_emits_non_secret_restore_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    archive = tmp_path / "universe.dump"
    archive.write_bytes(b"PGDMPfixture")
    inspection = MagicMock(
        path=archive,
        size_bytes=12,
        dumped_from_postgres="17.10",
        dumped_by_pg_dump="17.10",
        table_entries=42,
    )
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(fetchall=lambda: [("default",)]),
        MagicMock(fetchall=lambda: [(1, "yoke"), (3, "platform")]),
    ]
    monkeypatch.setattr(
        validator.universe_portability,
        "restore_universe",
        lambda selected_archive, selected_dsn: inspection,
    )
    monkeypatch.setattr(validator.db_backend, "connect_psycopg", lambda _dsn: conn)
    monkeypatch.setattr(validator, "missing_readiness_tables", lambda _conn: [])
    monkeypatch.setattr(
        validator,
        "fingerprint_portable_postgres_schema",
        lambda _conn: "fingerprint",
    )
    monkeypatch.setattr(
        validator.universe_portability,
        "user_content_counts",
        lambda _conn: {"items": 7},
    )

    report = validator.validate_archive_roundtrip(
        archive,
        "dbname=disposable",
    )

    assert report["organization"] == "default"
    assert report["projects"] == [
        {"id": 1, "slug": "yoke"},
        {"id": 3, "slug": "platform"},
    ]
    assert report["schema_fingerprint"] == "fingerprint"
    assert report["content_counts"] == {"items": 7}
    assert report["roundtrip"] is True
    conn.close.assert_called_once_with()


def test_roundtrip_requires_explicit_disposable_dsn(tmp_path: Path) -> None:
    archive = tmp_path / "universe.dump"
    archive.write_bytes(b"PGDMPfixture")

    with pytest.raises(validator.ArchiveValidationError, match="DSN is required"):
        validator.validate_archive_roundtrip(archive, "")
