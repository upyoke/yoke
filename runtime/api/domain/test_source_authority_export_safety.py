from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import source_authority_cutover as cutover
from yoke_core.domain import source_authority_export_artifacts as artifacts
from yoke_core.domain import source_authority_export_cutover as export_cutover
from yoke_core.domain.source_freeze_intent import write_owner_only_json


class _Result:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Connection:
    def execute(self, statement, params=None):
        if "pg_export_snapshot" in str(statement):
            return _Result(("00000003-0000001B-1",))
        return _Result((1,))

    def close(self):
        pass


def _receipt(digest: str) -> dict:
    return {
        "receipt_digest": digest,
        "tables": {},
        "strategy_rows": [],
        "project_capabilities": {
            "schema": "caps", "types": {}, "sha256": "c" * 64,
        },
        "capability_secrets": {
            "schema": "secrets", "types": {}, "sha256": "s" * 64,
        },
    }


def _non_lock_files(path: Path) -> list[Path]:
    return [entry for entry in path.iterdir() if not entry.name.endswith(".lock")]


def _configure_export(
    monkeypatch, tmp_path: Path, receipts_or_digests: list[str | dict],
) -> Path:
    archive = tmp_path / "source.dump"
    connections = iter((_Connection(), _Connection()))
    monkeypatch.setattr(
        cutover, "_admin_connection", lambda _dsn: next(connections),
    )
    monkeypatch.setattr(
        cutover, "_load_bundle",
        lambda *_a, **_kw: SimpleNamespace(
            database="source", database_oid=7, admin_role="admin",
            service_stop_receipt="stopped", original_dsn="original",
            cutover_dsn="cutover",
        ),
    )
    monkeypatch.setattr(
        cutover, "_validate_bundle_authority",
        lambda *_a: {"frozen_at": "2026-07-14T00:00:00Z"},
    )
    monkeypatch.setattr(
        cutover, "_database_identity",
        lambda _conn: {"database": "source", "database_oid": 7, "org": "yoke"},
    )
    monkeypatch.setattr(
        cutover.connect_fence, "connect_fence_status",
        lambda _conn: {"active": True, "unauthorized_sessions": []},
    )
    receipts = iter(
        _receipt(value) if isinstance(value, str) else value
        for value in receipts_or_digests
    )
    monkeypatch.setattr(
        export_cutover, "authority_receipt", lambda *_a, **_kw: next(receipts),
    )

    def export_universe(**kwargs):
        staged = Path(kwargs["out"])
        staged.write_bytes(b"PGDMPportable")
        return {
            "artifact": str(staged), "bytes": staged.stat().st_size,
            "format": "pg_dump-custom", "org": "yoke",
        }

    monkeypatch.setattr(
        export_cutover.universe_export, "export_universe", export_universe,
    )
    monkeypatch.setattr(
        export_cutover.universe_portability, "inspect_archive",
        lambda staged: SimpleNamespace(path=Path(staged)),
    )
    monkeypatch.setattr(
        export_cutover.universe_portability, "archive_catalog_receipt",
        lambda inspection: {
            "archive_sha256": export_cutover.file_sha256(inspection.path),
            "catalog_digest": "d" * 64,
        },
    )
    return archive


def test_fresh_post_dump_receipt_change_removes_archive(monkeypatch, tmp_path: Path):
    snapshot = _receipt("full")
    fresh = _receipt("full")
    fresh["capability_secrets"] = {
        "schema": "secrets", "types": {"github": {"count": 1}},
        "sha256": "changed",
    }
    archive = _configure_export(
        monkeypatch, tmp_path,
        ["compact", "compact", snapshot, fresh],
    )

    with pytest.raises(
        cutover.SourceAuthorityCutoverError,
        match="changed after the exported snapshot",
    ):
        cutover.export_quiesced(
            out=archive, credential_file=tmp_path / "credential.json",
        )

    assert _non_lock_files(tmp_path) == []


def test_sidecar_failure_leaves_no_valid_archive(monkeypatch, tmp_path: Path):
    archive = _configure_export(
        monkeypatch, tmp_path,
        ["compact", "compact", "full", "full"],
    )
    original_write = artifacts.write_owner_only_json
    writes = 0

    def fail_second(path, payload):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("simulated receipt storage failure")
        original_write(path, payload)

    monkeypatch.setattr(artifacts, "write_owner_only_json", fail_second)

    with pytest.raises(
        cutover.SourceAuthorityCutoverError,
        match="receipt set publication failed",
    ):
        cutover.export_quiesced(
            out=archive, credential_file=tmp_path / "credential.json",
        )

    assert _non_lock_files(tmp_path) == []


def test_archive_is_commit_marker_for_durable_receipt_set(tmp_path: Path):
    archive = tmp_path / "source.dump"
    artifact_set = artifacts.prepare_artifact_set(archive, org_slug="yoke")
    artifact_set.staged.write_bytes(b"PGDMPportable")
    intent = {"schema": "yoke.source-freeze/v1", "receipt_id": "a" * 64}
    receipt = {"freeze_intent": intent, "source_authority": {}}

    artifacts.publish_artifact_set(
        artifact_set, intent=intent, receipt=receipt,
    )

    assert archive.read_bytes() == b"PGDMPportable"
    assert artifact_set.final_intent.exists()
    assert artifact_set.final_receipt.exists()
    assert not artifact_set.staged.exists()


def test_orphan_receipts_without_archive_are_recovered(tmp_path: Path):
    archive = tmp_path / "source.dump"
    intent_path = archive.with_suffix(
        archive.suffix + ".source-freeze-intent.json"
    )
    receipt_path = archive.with_suffix(
        archive.suffix + ".source-freeze-receipt.json"
    )
    intent = {"schema": "yoke.source-freeze/v1", "receipt_id": "a" * 64}
    write_owner_only_json(intent_path, intent)
    write_owner_only_json(receipt_path, {"freeze_intent": intent})

    artifact_set = artifacts.prepare_artifact_set(archive, org_slug="yoke")

    assert artifact_set.final == archive
    assert not intent_path.exists()
    assert not receipt_path.exists()
    artifacts.cleanup_staged(artifact_set)


def test_crashed_staging_archive_is_removed_under_publication_lock(
    tmp_path: Path,
):
    archive = tmp_path / "source.dump"
    staged = tmp_path / ".source.dump.0123456789abcdef.partial"
    staged.write_bytes(b"PGDMPprivate")
    staged.chmod(0o600)

    artifact_set = artifacts.prepare_artifact_set(archive, org_slug="yoke")

    assert not staged.exists()
    artifacts.cleanup_staged(artifact_set)


def test_active_export_lock_prevents_orphan_receipt_recovery(tmp_path: Path):
    archive = tmp_path / "source.dump"
    first = artifacts.prepare_artifact_set(archive, org_slug="yoke")
    intent = {"schema": "yoke.source-freeze/v1", "receipt_id": "a" * 64}
    write_owner_only_json(first.final_intent, intent)

    try:
        with pytest.raises(
            artifacts.SourceExportArtifactError,
            match="already active",
        ):
            artifacts.prepare_artifact_set(archive, org_slug="yoke")
        assert first.final_intent.exists()
    finally:
        first.final_intent.unlink(missing_ok=True)
        artifacts.cleanup_staged(first)
