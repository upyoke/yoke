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
        source_name = source.info.dbname
        source_oid = source.execute(
            "SELECT oid FROM pg_database WHERE datname=current_database()"
        ).fetchone()[0]
        source.commit()
        output = []
        with psycopg.connect(dsn) as other:
            other.execute("SELECT 1")
            report = universe_export.export_universe(
                dsn=dsn,
                out=tmp_path / "move.tar",
                pause_source=True,
                emit=output.append,
            )
            try:
                assert pause.is_paused(dsn)
                with pytest.raises(psycopg.OperationalError):
                    psycopg.connect(dsn)
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
                assert receipt["freeze_intent"]["database"]["name"] == source_name
                assert receipt["freeze_intent"]["database"]["oid"] == source_oid
                assert any("artifacts-manifest.json" in line for line in output)
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


def test_unwritable_destination_refuses_before_pausing(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    destination = tmp_path / "read-only"
    destination.mkdir(mode=0o500)
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        try:
            with pytest.raises(
                universe_export.UniverseExportError,
                match="universe_export_destination_unavailable",
            ):
                universe_export.export_universe(
                    dsn=dsn, out=destination / "move.tar", pause_source=True
                )
            assert not pause.is_paused(dsn)
            assert source.execute("SELECT 42").fetchone()[0] == 42
            with psycopg.connect(dsn) as other:
                assert other.execute("SELECT 42").fetchone()[0] == 42
        finally:
            destination.chmod(0o700)


def test_resume_cannot_race_export(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    dsn = "host=localhost dbname=isolated"
    from concurrent.futures import ThreadPoolExecutor

    with pause.operation(dsn), ThreadPoolExecutor(max_workers=1) as competing:
        result = competing.submit(pause.resume, dsn)
        with pytest.raises(pause.UniversePausedError, match="universe_source_busy"):
            result.result()


def test_pause_persists_service_recovery_before_stopping(monkeypatch, tmp_path):
    import json
    from yoke_core.domain import universe_source_services as services

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    record = {"relay_environment": "isolated"}
    events = []
    monkeypatch.setattr(services, "plan", lambda _dsn: record)
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]

        def stop(value):
            assert value == json.loads(pause._marker(dsn).read_text())
            assert value["relay_environment"] == "isolated"
            events.append("stopped")

        def start(value):
            assert pause.is_paused(dsn)
            assert value["relay_environment"] == "isolated"
            events.append("started")

        monkeypatch.setattr(services, "stop", stop)
        monkeypatch.setattr(services, "start", start)
        pause.pause(dsn)
        pause.resume(dsn)
    assert events == ["stopped", "started"]


def test_failed_resume_preparation_keeps_source_paused(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database() as source:
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        pause.pause(dsn)
        try:
            with pytest.raises(
                pause.UniversePausedError, match="universe_resume_failed"
            ):
                with pause.resuming_source(dsn):
                    raise RuntimeError("schema preparation failed")
            with pytest.raises(pause.UniversePausedError):
                db_backend.connect_psycopg(dsn)
        finally:
            pause.resume(dsn)


def test_startup_waits_until_export_releases_source(monkeypatch, tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    monkeypatch.setenv("YOKE_SERVER_MODE", "self-host")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    dsn = "host=localhost dbname=serialized-startup"
    attempted = Event()
    order = []

    def start():
        attempted.set()
        with pause.startup_access(dsn):
            order.append("startup admitted")

    with ThreadPoolExecutor(max_workers=1) as worker:
        with pause.operation(dsn):
            future = worker.submit(start)
            assert attempted.wait(5)
            order.append("export finished")
        future.result(timeout=5)
    assert order == ["export finished", "startup admitted"]
