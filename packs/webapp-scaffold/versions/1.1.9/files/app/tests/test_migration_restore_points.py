"""Migration restore-point failure and input validation checks."""

import os
import sqlite3
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.migrations.migrate import migrate  # noqa: E402
from utils import db as db_utils  # noqa: E402


def test_restore_point_failure_removes_the_private_partial(tmp_path):
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)

    class FailingBackup:
        def execute(self, statement):
            return conn.execute(statement)

        def backup(self, _target):
            raise RuntimeError("backup interrupted")

    with pytest.raises(RuntimeError, match="backup interrupted"):
        db_utils.establish_migration_restore_point(
            FailingBackup(),
            (SimpleNamespace(name="0001_change"),),
        )

    backup_dir = tmp_path / "migration-backups"
    assert list(backup_dir.iterdir()) == []
    conn.close()


def test_blank_external_restore_point_is_refused_before_database_work(tmp_path):
    database = tmp_path / "must-not-be-created.db"

    with pytest.raises(RuntimeError, match="non-empty identifier"):
        migrate(
            db_path=database,
            running_version="1.0.0",
            external_restore_point="   ",
        )

    assert not database.exists()


def test_snapshot_uses_sqlite_sync_without_manual_filesystem_operations(
    tmp_path, monkeypatch
):
    database = tmp_path / "app.db"
    conn = sqlite3.connect(database)
    conn.execute("CREATE TABLE marks (name TEXT)")
    conn.execute("INSERT INTO marks VALUES ('before')")
    conn.commit()
    real_connect = sqlite3.connect
    sync_settings = []

    def connect(*args, **kwargs):
        backup = real_connect(*args, **kwargs)
        backup.set_trace_callback(sync_settings.append)
        return backup

    def unsupported(*_args, **_kwargs):
        raise AssertionError("manual filesystem synchronization or chmod")

    monkeypatch.setattr(db_utils.sqlite3, "connect", connect)
    monkeypatch.setattr(db_utils.os, "fsync", unsupported)
    monkeypatch.setattr(db_utils.os, "chmod", unsupported)
    restore = db_utils.establish_migration_restore_point(conn, ())
    backup = real_connect(restore)
    assert "PRAGMA synchronous = FULL" in sync_settings
    assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert backup.execute("SELECT name FROM marks").fetchall() == [("before",)]
    backup.close()
    conn.close()
