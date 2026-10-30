"""Snapshot isolation and the portable source-pause receipt contract."""

import os
import subprocess
from pathlib import Path

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend, universe_archive
from yoke_core.domain import universe_snapshot_archive as engine


@pytest.mark.parametrize("writers_stopped", [False, True])
def test_snapshot_excludes_later_write_and_carries_writer_state(
    monkeypatch, tmp_path, writers_stopped
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    real_dump = engine.universe_portability.dump_universe

    def dump_after_write(dsn, destination, **kwargs):
        with psycopg.connect(dsn, autocommit=True) as writer:
            writer.execute(
                "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
                "VALUES (91001, 'after-snapshot', 'After snapshot', 'AFTER', now())"
            )
        return real_dump(dsn, destination, **kwargs)

    monkeypatch.setattr(engine.universe_portability, "dump_universe", dump_after_write)
    with pg_testdb.test_database() as source:
        source.commit()
        report = engine.snapshot_archive(
            dsn=os.environ[db_backend.PG_DSN_ENV],
            out=tmp_path / "snapshot.tar",
            writers_stopped=writers_stopped,
        )
        assert (
            source.execute("SELECT slug FROM projects WHERE id=91001").fetchone()[0]
            == "after-snapshot"
        )
    dump, receipt = universe_archive.unpack_universe_archive(
        Path(report["artifact"]), tmp_path / "unpacked", max_dump_bytes=1 << 30
    )
    data = subprocess.run(
        ["pg_restore", "--data-only", "--table=projects", "--file=-", str(dump)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "after-snapshot" not in data
    intent = receipt["freeze_intent"]
    assert intent["zero_writable_app_sessions"] is writers_stopped
    # Hosted import accepts only explicit proof of stopped writers.
    assert (intent.get("zero_writable_app_sessions") is True) is writers_stopped


def test_archive_cap_refuses_before_replacing_destination(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    destination = tmp_path / "bounded.tar"
    destination.write_bytes(b"previous archive")
    with pg_testdb.test_database():
        with pytest.raises(
            engine.UniverseExportError, match="universe_export_size_limit"
        ):
            engine.snapshot_archive(
                dsn=os.environ[db_backend.PG_DSN_ENV],
                out=destination,
                writers_stopped=False,
                max_bytes=1,
            )
    assert destination.read_bytes() == b"previous archive"


@pytest.mark.parametrize("writers_stopped", [False, True])
def test_archive_receipt_matches_hosted_admission_fixture(
    monkeypatch, tmp_path, writers_stopped
):
    from types import SimpleNamespace
    from runtime.api.fixtures.hosted_freeze_receipt import assert_hosted_receipt

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database():
        report = engine.snapshot_archive(
            dsn=os.environ[db_backend.PG_DSN_ENV],
            out=tmp_path / "move.tar",
            writers_stopped=writers_stopped,
            include_artifacts=False,
        )
    _, receipt = universe_archive.unpack_universe_archive(
        Path(report["artifact"]), tmp_path / "hosted", max_dump_bytes=1 << 30
    )
    intent = SimpleNamespace(
        source_freeze_receipt=receipt["freeze_intent"],
        archive_sha256=report["sha256"],
        environment_capability_types={"aws-admin", "github"},
    )
    if writers_stopped:
        assert_hosted_receipt(intent)
    else:
        with pytest.raises(ValueError, match="source freeze intent is invalid"):
            assert_hosted_receipt(intent)


def test_manifest_receipt_exposes_current_hosted_consumer_gap(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from runtime.api.fixtures.hosted_freeze_receipt import assert_hosted_receipt

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database():
        report = engine.snapshot_archive(
            dsn=os.environ[db_backend.PG_DSN_ENV],
            out=tmp_path / "with-files.tar",
            writers_stopped=True,
        )
    _, receipt = universe_archive.unpack_universe_archive(
        Path(report["artifact"]), tmp_path / "hosted", max_dump_bytes=1 << 30
    )
    assert receipt["freeze_intent"]["zero_writable_app_sessions"] is True
    assert receipt["freeze_intent"]["archive"]["artifacts_manifest_sha256"]
    with pytest.raises(ValueError, match="source freeze intent is invalid"):
        assert_hosted_receipt(
            SimpleNamespace(
                source_freeze_receipt=receipt["freeze_intent"],
                archive_sha256=report["sha256"],
                environment_capability_types={"aws-admin", "github"},
            )
        )
