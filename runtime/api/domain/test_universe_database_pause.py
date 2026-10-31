"""A database pause stops clients that know nothing about Yoke markers."""

import json
import os

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import db_backend, universe_database_pause as database
from yoke_core.domain import universe_source_pause as pause


def test_raw_clients_cannot_reconnect_until_resume(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database() as source:
        source.execute("CREATE TABLE pause_probe (value text)")
        source.execute("INSERT INTO pause_probe VALUES ('frozen')")
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        pause.pause(dsn)
        try:
            state = json.loads(pause._marker(dsn).read_text())["database_pause"]
            with pytest.raises(
                psycopg.OperationalError, match="not currently accepting connections"
            ):
                psycopg.connect(dsn)
            # These connections never import Yoke's connection admission code.
            with psycopg.connect(database.maintenance_dsn(dsn)) as unrelated:
                assert unrelated.execute("SELECT 1").fetchone() == (1,)
            with pause.pause_owner(), db_backend.connect_psycopg(dsn) as frozen:
                assert frozen.info.dbname == state["copy"]
                assert frozen.execute("SELECT value FROM pause_probe").fetchone() == (
                    "frozen",
                )
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    frozen.execute("INSERT INTO pause_probe VALUES ('must fail')")
            database.confirm(dsn, state)
        finally:
            pause.resume(dsn)
        with psycopg.connect(dsn) as resumed:
            resumed.execute("INSERT INTO pause_probe VALUES ('resumed')")
            assert resumed.execute("SELECT count(*) FROM pause_probe").fetchone() == (
                2,
            )


def test_failed_resume_refences_source_and_refreshes_frozen_copy(monkeypatch, tmp_path):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    with pg_testdb.test_database() as source:
        source.execute("CREATE TABLE pause_probe (value text)")
        source.commit()
        dsn = os.environ[db_backend.PG_DSN_ENV]
        pause.pause(dsn)
        try:
            with pytest.raises(
                pause.UniversePausedError, match="universe_resume_failed"
            ):
                with pause.resuming_source(dsn):
                    with psycopg.connect(dsn) as reopened:
                        reopened.execute("INSERT INTO pause_probe VALUES ('kept')")
                    raise RuntimeError("preparation failed")
            with pytest.raises(psycopg.OperationalError):
                psycopg.connect(dsn)
            with pause.pause_owner(), db_backend.connect_psycopg(dsn) as frozen:
                assert frozen.execute("SELECT value FROM pause_probe").fetchone() == (
                    "kept",
                )
        finally:
            pause.resume(dsn)
