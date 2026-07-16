"""Tests for the universe-export engine's one-file tar artifact.

The real-artifact tests run pg_dump/pg_restore from ``PATH`` against the
test cluster (an isolated machine home keeps the embedded-binaries
resolver empty). The active-connection sanction contract lives in
``test_universe_export_authority.py``.
"""

from __future__ import annotations

import contextlib
import os
import re
import subprocess
import tarfile
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_core.domain import universe_archive
from yoke_core.domain import universe_export as ux
from yoke_core.domain.source_freeze_intent import file_sha256


@pytest.fixture(autouse=True)
def _isolated_machine_home(monkeypatch, tmp_path):
    monkeypatch.setenv(machine_runtime.HOME_ENV, str(tmp_path / "machine-home"))
    monkeypatch.delenv(machine_runtime.CONFIG_FILE_ENV, raising=False)
    monkeypatch.delenv("YOKE_ENV", raising=False)


@contextlib.contextmanager
def _schema_loaded_universe():
    """Yield ``(conn, dsn)`` for a fresh schema-loaded disposable database.

    The fixture schema seeds the default org identity card, so the
    database looks like a bootstrapped universe to the export probe.
    """
    from runtime.api.fixtures import pg_testdb
    from yoke_core.domain import db_backend

    with pg_testdb.test_database() as conn:
        yield conn, os.environ[db_backend.PG_DSN_ENV]


def _unpack(artifact: Path, work_dir: Path) -> tuple[Path, dict]:
    return universe_archive.unpack_universe_archive(
        artifact,
        work_dir,
        max_dump_bytes=1 << 30,
    )


def test_default_artifact_name_embeds_slug_and_utc_timestamp():
    moment = datetime(2026, 7, 6, 12, 34, 56, tzinfo=timezone.utc)
    assert ux.default_artifact_name("default", moment) == (
        "default-universe-20260706T123456Z.tar"
    )


def test_default_artifact_name_sanitizes_hostile_slug():
    moment = datetime(2026, 7, 6, 12, 34, 56, tzinfo=timezone.utc)
    name = ux.default_artifact_name("my org/../etc", moment)
    assert name == "my-org-..-etc-universe-20260706T123456Z.tar"
    assert "/" not in name


def test_export_produces_one_receipt_carrying_tar_artifact(tmp_path):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    emitted: list[str] = []
    with _schema_loaded_universe() as (conn, dsn):
        conn.execute(
            "INSERT INTO capability_secrets "
            "(project_id, type, key, value, source, created_at) "
            "VALUES (1, 'github', 'token', 'must-not-export', 'literal', now())"
        )
        conn.commit()
        report = ux.export_universe(dsn=dsn, out=out_dir, emit=emitted.append)

    artifact = Path(report["artifact"])
    assert artifact.parent == out_dir
    assert artifact.name.startswith("default-universe-")
    assert artifact.name.endswith(ux.ARTIFACT_SUFFIX)
    assert artifact.is_file()
    assert report["bytes"] == artifact.stat().st_size > 0
    assert report["format"] == ux.ARTIFACT_FORMAT
    assert report["org"] == "default"
    assert any("universe-export" in line for line in emitted)

    with tarfile.open(artifact, mode="r:") as reader:
        # Receipt first: streaming readers verify intent before the payload.
        assert [member.name for member in reader.getmembers()] == [
            universe_archive.ARCHIVE_MEMBER_RECEIPT,
            universe_archive.ARCHIVE_MEMBER_DUMP,
        ]

    dump, receipt = _unpack(artifact, tmp_path / "unpacked")
    # The receipt travels inside the artifact and binds the exact payload.
    intent = receipt["freeze_intent"]
    assert intent["schema"] == "yoke.source-freeze/v1"
    assert intent["database"]["org"] == "default"
    assert intent["archive"]["sha256"] == file_sha256(dump) == report["sha256"]
    assert intent["archive"]["bytes"] == dump.stat().st_size
    assert intent["zero_writable_app_sessions"] is False
    assert intent["receipt_id"] == report["receipt_id"]
    assert receipt["catalog"]["archive_sha256"] == intent["archive"]["sha256"]
    assert receipt["source_authority"]["receipt_digest"]

    listing = subprocess.run(
        ["pg_restore", "--list", str(dump)],
        capture_output=True,
        text=True,
    )
    assert listing.returncode == 0, listing.stderr
    assert "organizations" in listing.stdout
    assert "actors" in listing.stdout
    assert "TABLE DATA public capability_secrets" not in listing.stdout
    assert "SEQUENCE SET public capability_secrets_id_seq" not in listing.stdout


def test_export_leaves_no_staged_payload_beside_the_artifact(tmp_path):
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=out_dir)

    assert [entry.name for entry in out_dir.iterdir()] == [
        Path(report["artifact"]).name
    ]


def test_export_honors_explicit_out_file_path(tmp_path):
    dest = tmp_path / "nested" / "graduation.tar"
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=dest)

    assert Path(report["artifact"]) == dest
    assert dest.is_file() and dest.stat().st_size > 0


def test_export_trailing_separator_creates_directory(tmp_path):
    """``--out ~/backups/`` with the directory absent means directory mode:
    the directory is created and the artifact lands inside it — never a
    suffixless file named after the directory."""
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=f"{tmp_path / 'backups'}/")

    backups = tmp_path / "backups"
    assert backups.is_dir()
    artifact = Path(report["artifact"])
    assert artifact.parent == backups
    assert artifact.name.endswith(ux.ARTIFACT_SUFFIX)
    assert artifact.is_file() and artifact.stat().st_size > 0


def test_resolve_destination_routes_directory_vs_file(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()

    # Existing directory (no trailing separator) -> directory mode.
    dest = ux.resolve_export_destination(existing, "default")
    assert dest.parent == existing
    assert dest.name.endswith(ux.ARTIFACT_SUFFIX)

    # Trailing separator on a nonexistent directory -> directory mode,
    # created with parents.
    dest = ux.resolve_export_destination(
        f"{tmp_path / 'made' / 'deep'}/", "default",
    )
    assert (tmp_path / "made" / "deep").is_dir()
    assert dest.parent == tmp_path / "made" / "deep"

    # Anything else -> file mode; the parent is created for the artifact.
    explicit = tmp_path / "files" / "x.tar"
    assert ux.resolve_export_destination(explicit, "default") == explicit
    assert explicit.parent.is_dir()
    assert not explicit.exists()


def test_export_refuses_database_without_org_card(tmp_path):
    with _schema_loaded_universe() as (conn, dsn):
        conn.execute("DELETE FROM organizations")
        conn.commit()
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=tmp_path)
    assert "no organization identity card" in str(excinfo.value)


def test_export_raises_typed_error_when_pg_dump_missing(monkeypatch, tmp_path):
    with _schema_loaded_universe() as (_conn, dsn):
        # Isolated machine home has no embedded binaries; an empty PATH dir
        # removes the fallback, mirroring the local-universe resolver tests.
        monkeypatch.setenv("PATH", str(tmp_path / "no-binaries-here"))
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=tmp_path)
    message = str(excinfo.value)
    assert "pg_dump is missing" in message
    assert "yoke local-postgres start" in message


def test_export_prefers_embedded_pg_dump_and_cleans_failed_staging(
    tmp_path,
):
    """A fake embedded pg_dump proves installed-binaries-first resolution;
    its failure exit proves the stderr surfacing plus staged-payload and
    artifact cleanup contract."""
    from yoke_core.domain import postgres_binaries

    bin_dir = postgres_binaries.version_dir() / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "initdb").write_text("#!/bin/sh\n", encoding="utf-8")
    fake_pg_dump = bin_dir / "pg_dump"
    fake_pg_dump.write_text(
        "#!/bin/sh\necho 'pg_dump: error: simulated failure' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_pg_dump.chmod(0o755)
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    dest = out_dir / "x.tar"
    with _schema_loaded_universe() as (_conn, dsn):
        with pytest.raises(ux.UniverseExportError) as excinfo:
            ux.export_universe(dsn=dsn, out=dest)
    assert "redacted" in str(excinfo.value)
    assert not dest.exists()
    assert list(out_dir.iterdir()) == []


def test_export_binds_dump_and_receipt_to_one_exported_snapshot(
    monkeypatch, tmp_path,
):
    """The engine derives the snapshot itself and hands pg_dump exactly
    that snapshot; the receipt is computed on the same frozen view."""
    observed: dict[str, object] = {}

    def fake_dump(dsn, destination, **kwargs):
        observed.update(
            dsn=dsn,
            destination=Path(destination),
            timeout_s=kwargs["timeout_s"],
            snapshot=kwargs["snapshot"],
        )
        Path(destination).write_bytes(b"PGDMP")
        return SimpleNamespace(
            size_bytes=5,
            archive_sha256=file_sha256(Path(destination)),
            catalog_digest="d" * 64,
            catalog_tables=("organizations",),
            catalog_sequences=(),
            table_entries=1,
            path=Path(destination),
        )

    monkeypatch.setattr(ux.universe_portability, "dump_universe", fake_dump)
    dest = tmp_path / "snapshot-bound.tar"
    with _schema_loaded_universe() as (_conn, dsn):
        report = ux.export_universe(dsn=dsn, out=dest)

    assert observed["dsn"] == dsn
    assert re.fullmatch(
        r"[0-9A-Fa-f]+(?:-[0-9A-Fa-f]+)+", str(observed["snapshot"])
    )
    assert observed["timeout_s"] == ux.DEFAULT_EXPORT_TIMEOUT_S
    dump, receipt = _unpack(dest, tmp_path / "unpacked")
    assert dump.read_bytes() == b"PGDMP"
    assert receipt["freeze_intent"]["archive"]["sha256"] == report["sha256"]


def test_export_refuses_when_universe_changes_mid_dump(monkeypatch, tmp_path):
    """A write landing between the before/after authority receipts is a
    refusal, and no artifact or staging file survives it."""
    from yoke_core.domain import source_authority_receipts

    def mutating_dump(dsn, destination, **_kwargs):
        import psycopg

        with psycopg.connect(dsn, autocommit=True) as writer:
            writer.execute(
                "INSERT INTO projects "
                "(id, slug, name, public_item_prefix, created_at) "
                "VALUES (91001, 'mid-dump', 'Mid dump', 'MID', now())"
            )
        Path(destination).write_bytes(b"PGDMP")
        return SimpleNamespace(
            size_bytes=5,
            archive_sha256="a" * 64,
            catalog_digest="d" * 64,
            catalog_tables=("organizations",),
            catalog_sequences=(),
            table_entries=1,
            path=Path(destination),
        )

    receipts: list[str] = []
    original_receipt = source_authority_receipts.authority_receipt

    def tracking_receipt(conn, **kwargs):
        # The export's snapshot connection sees a frozen view, so make the
        # after-receipt read from a fresh connection to observe the write.
        import psycopg

        from yoke_core.domain import db_backend

        receipts.append("called")
        if len(receipts) == 1:
            return original_receipt(conn, **kwargs)
        with psycopg.connect(os.environ[db_backend.PG_DSN_ENV]) as fresh:
            return original_receipt(fresh, **kwargs)

    monkeypatch.setattr(ux.universe_portability, "dump_universe", mutating_dump)
    monkeypatch.setattr(
        source_authority_receipts, "authority_receipt", tracking_receipt,
    )
    out_dir = tmp_path / "exports"
    out_dir.mkdir()
    dest = out_dir / "changed.tar"
    with _schema_loaded_universe() as (_conn, dsn):
        with pytest.raises(ux.UniverseExportError, match="changed while"):
            ux.export_universe(dsn=dsn, out=dest)
    assert list(out_dir.iterdir()) == []
