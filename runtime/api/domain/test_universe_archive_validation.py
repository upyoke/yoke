from pathlib import Path
from unittest.mock import MagicMock

import pytest

from yoke_core.domain import universe_archive
from yoke_core.domain import universe_archive_validation as validator
from yoke_core.domain.source_freeze_intent import file_sha256


def _artifact(tmp_path: Path, *, forge_sha: str | None = None) -> Path:
    dump = tmp_path / "staged.dump"
    dump.write_bytes(b"PGDMPfixture")
    receipt = {
        "freeze_intent": {
            "schema": "yoke.source-freeze/v1",
            "receipt_id": "b" * 64,
            "database": {"name": "yoke", "oid": 7, "org": "default"},
            "frozen_at": "2026-07-14T00:00:00Z",
            "archive": {
                "sha256": forge_sha or file_sha256(dump),
                "bytes": dump.stat().st_size,
                "catalog_digest": "d" * 64,
            },
        },
        "source_authority": {"receipt_digest": "stable"},
    }
    artifact = tmp_path / "default-universe.tar"
    universe_archive.pack_universe_archive(dump, receipt, artifact)
    return artifact


def _inspection(tmp_path: Path) -> MagicMock:
    return MagicMock(
        path=tmp_path / "staged.dump",
        size_bytes=12,
        dumped_from_postgres="17.10",
        dumped_by_pg_dump="17.10",
        table_entries=42,
        archive_sha256="a" * 64,
        catalog_tables=("items",),
        catalog_sequences=("items_id_seq",),
        catalog_digest="d" * 64,
    )


def test_inspection_verifies_the_enclosed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    monkeypatch.setattr(
        validator.universe_portability,
        "inspect_archive",
        lambda _dump: _inspection(tmp_path),
    )

    report = validator.inspect_archive(artifact)

    assert report["ok"] is True
    assert report["archive"] == str(artifact.resolve())
    assert report["bytes"] == artifact.stat().st_size
    assert report["table_entries"] == 42
    assert report["receipt_verified"] is True
    assert report["receipt"] == {
        "receipt_id": "b" * 64,
        "org": "default",
        "frozen_at": "2026-07-14T00:00:00Z",
    }


def test_inspection_refuses_receipt_that_does_not_bind_the_dump(
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path, forge_sha="0" * 64)
    with pytest.raises(
        universe_archive.UniverseArchiveError, match="does not match"
    ):
        validator.inspect_archive(artifact)


def test_roundtrip_emits_non_secret_restore_receipts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = _artifact(tmp_path)
    conn = MagicMock()
    conn.execute.side_effect = [
        MagicMock(fetchall=lambda: [("default",)]),
        MagicMock(fetchall=lambda: [(1, "yoke"), (3, "platform")]),
    ]
    restored = {}

    def fake_restore(selected_dump, selected_dsn):
        restored.update(dump=Path(selected_dump), dsn=selected_dsn)
        return _inspection(tmp_path)

    monkeypatch.setattr(
        validator.universe_portability, "restore_universe", fake_restore,
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
    monkeypatch.setattr(
        validator,
        "authority_receipt",
        lambda _conn, **_kwargs: {"receipt_digest": "whole-authority"},
    )

    report = validator.validate_archive_roundtrip(
        artifact,
        "dbname=disposable",
    )

    assert restored["dump"].name == universe_archive.ARCHIVE_MEMBER_DUMP
    assert restored["dsn"] == "dbname=disposable"
    assert report["organization"] == "default"
    assert report["projects"] == [
        {"id": 1, "slug": "yoke"},
        {"id": 3, "slug": "platform"},
    ]
    assert report["schema_fingerprint"] == "fingerprint"
    assert report["content_counts"] == {"items": 7}
    assert report["roundtrip"] is True
    assert report["receipt_verified"] is True
    assert report["authority"] == {"receipt_digest": "whole-authority"}
    conn.close.assert_called_once_with()


def test_roundtrip_requires_explicit_disposable_dsn(tmp_path: Path) -> None:
    artifact = _artifact(tmp_path)

    with pytest.raises(validator.ArchiveValidationError, match="DSN is required"):
        validator.validate_archive_roundtrip(artifact, "")
