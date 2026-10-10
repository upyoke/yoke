"""Quiesced source export receipt and immutable tar custody."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_source_authority_cutover import _Conn, _Result
from yoke_core.domain import source_authority_cutover as cutover


def test_quiesced_export_emits_one_receipt_carrying_tar_and_refuses_mutable_source(
    monkeypatch,
    tmp_path: Path,
):
    import tarfile

    conn = _Conn()
    archive = tmp_path / "source.tar"
    from yoke_core.domain import source_authority_export_cutover as export_cutover
    from yoke_core.domain import universe_archive

    monkeypatch.setattr(
        export_cutover,
        "authority_receipt",
        lambda _conn, **_kw: {
            "receipt_digest": "stable",
            "tables": {},
            "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )

    monkeypatch.setattr(cutover, "_admin_connection", lambda _dsn: conn)
    bundle = SimpleNamespace(
        database="source",
        database_oid=7,
        admin_role="admin",
        service_stop_receipt="service-stopped",
        original_dsn="secret-dsn",
        cutover_dsn="rotated-dsn",
    )
    monkeypatch.setattr(cutover, "_load_bundle", lambda *_a, **_kw: bundle)
    monkeypatch.setattr(
        cutover,
        "_validate_bundle_authority",
        lambda *_a: {
            "frozen_at": "2026-07-14T00:00:00Z",
            "service_stop_receipt": "service-stopped",
            "policy": {},
        },
    )
    fence_active = {"active": True, "unauthorized_sessions": []}
    monkeypatch.setattr(
        cutover.connect_fence,
        "connect_fence_status",
        lambda _conn: fence_active,
    )
    monkeypatch.setattr(
        cutover.connect_fence,
        "fence_state",
        lambda _conn: {
            "frozen_at": "2026-07-14T00:00:00Z",
            "service_stop_receipt": "service-stopped",
            "policy": {},
        },
    )
    monkeypatch.setattr(
        cutover,
        "authority_receipt",
        lambda _conn, **_kw: {
            "receipt_digest": "stable",
            "tables": {},
            "strategy_rows": [],
            "project_capabilities": {"schema": "caps", "types": {}, "sha256": "c"},
            "capability_secrets": {"schema": "secrets", "types": {}, "sha256": "s"},
        },
    )

    def dump_universe(_dsn, destination, **_kwargs):
        staged = Path(destination)
        staged.write_bytes(b"PGDMPportable")
        return SimpleNamespace(
            path=staged,
            archive_sha256=export_cutover.file_sha256(staged),
            size_bytes=staged.stat().st_size,
            catalog_tables=("items",),
            catalog_sequences=("items_id_seq",),
            catalog_digest="catalog",
            table_entries=2,
        )

    monkeypatch.setattr(
        export_cutover.universe_portability,
        "dump_universe",
        dump_universe,
    )
    monkeypatch.setattr(
        cutover,
        "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    original_execute = conn.execute

    def execute(statement, params=None):
        if "pg_export_snapshot" in str(statement):
            return _Result(("00000003-0000001B-1",))
        return original_execute(statement, params)

    conn.execute = execute

    report = cutover.export_quiesced(
        out=archive,
        credential_file=tmp_path / "cutover.json",
    )

    assert report["stable_watermarks"] is True
    assert report["source_authority"]["receipt_digest"] == "stable"
    assert report["snapshot_proof"]["isolation"] == "repeatable-read-read-only"
    assert len(report["sha256"]) == 64
    assert report["freeze_intent"]["schema"] == "yoke.source-freeze/v2"
    assert report["freeze_intent"]["zero_writable_app_sessions"] is True
    assert "capability_secrets" not in report["catalog"]["tables"]
    assert set(report["freeze_intent"]) == {
        "schema",
        "receipt_id",
        "database",
        "frozen_at",
        "authority_digest",
        "updated_at_watermark",
        "strategy_sha256",
        "archive",
        "zero_writable_app_sessions",
        "project_capabilities",
        "capability_secrets",
    }
    assert "secret-dsn" not in str(report)

    # One artifact, no sidecars: the receipt travels inside the tar.
    assert report["artifact"] == str(archive)
    assert report["bytes"] == archive.stat().st_size
    assert sorted(entry.name for entry in tmp_path.iterdir()) == [
        archive.name,
    ]
    with tarfile.open(archive, mode="r:") as reader:
        # Receipt first: streaming readers verify intent before the payload.
        assert [member.name for member in reader.getmembers()] == [
            universe_archive.ARCHIVE_MEMBER_RECEIPT,
            universe_archive.ARCHIVE_MEMBER_DUMP,
        ]
    dump, receipt = universe_archive.unpack_universe_archive(
        archive,
        tmp_path / "unpacked",
        max_dump_bytes=1 << 20,
    )
    assert dump.read_bytes() == b"PGDMPportable"
    assert receipt["freeze_intent"] == report["freeze_intent"]
    assert (
        universe_archive.verify_receipt_binds_dump(receipt, dump)["sha256"]
        == report["sha256"]
    )

    monkeypatch.setattr(
        cutover.connect_fence,
        "connect_fence_status",
        lambda _conn: {"active": False},
    )
    archive.unlink()
    with pytest.raises(cutover.SourceAuthorityCutoverError, match="active quiesce"):
        cutover.export_quiesced(
            out=archive,
            credential_file=tmp_path / "cutover.json",
        )
    assert not archive.exists()
