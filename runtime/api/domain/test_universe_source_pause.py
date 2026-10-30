"""Source pause stops existing clients and refuses new writer connections."""

import os
from pathlib import Path

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend, universe_archive, universe_export
from yoke_core.domain import universe_source_pause as pause


def test_pause_drains_clients_and_resume_reopens_source(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        with psycopg.connect(dsn) as other:
            other.execute("SELECT 1")
            report = universe_export.export_universe(
                dsn=dsn, out=tmp_path / "move.tar", pause_source=True
            )
            try:
                assert pause.is_paused(dsn)
                with pytest.raises(psycopg.OperationalError):
                    other.execute("SELECT 1")
                for connect in (
                    db_backend.connect,
                    lambda: db_backend.connect_psycopg(dsn),
                ):
                    with pytest.raises(
                        pause.UniversePausedError, match="universe resume"
                    ):
                        connect()
                _, receipt = universe_archive.unpack_universe_archive(
                    Path(report["artifact"]),
                    tmp_path / "unpacked",
                    max_dump_bytes=1 << 30,
                )
                assert receipt["freeze_intent"]["zero_writable_app_sessions"] is True
            finally:
                pause.resume(dsn)
        with db_backend.connect_psycopg(dsn) as restored:
            assert restored.execute("SELECT 42").fetchone()[0] == 42


def test_failed_export_leaves_source_paused(monkeypatch, tmp_path):
    from yoke_core.domain import universe_snapshot_archive

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))

    def fail(**_kwargs):
        raise universe_export.UniverseExportError("dump failed")

    monkeypatch.setattr(universe_snapshot_archive, "snapshot_archive", fail)
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        try:
            with pytest.raises(
                universe_export.UniverseExportError, match="dump failed"
            ):
                universe_export.export_universe(
                    dsn=dsn, out=tmp_path / "failed.tar", pause_source=True
                )
            assert pause.is_paused(dsn)
            assert not (tmp_path / "failed.tar").exists()
        finally:
            pause.resume(dsn)
