"""Exception-path backup tests for the migration harness."""

from __future__ import annotations

import os
import re
from pathlib import Path
from unittest import mock

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.migration_harness import (
    MigrationBackupError,
    _run_backup,
    create_exception_backup,
    record_audit_fingerprint,
)


@pytest.fixture
def initialized_db(tmp_path: Path) -> str:
    with init_test_db(tmp_path) as db_path:
        yield db_path


class TestExceptionPathBackup:
    """``backup_reason`` drives canonical exception-path backups."""

    def test_backup_reason_creates_canonical_backup_and_records_path(
        self, tmp_path: Path, initialized_db: str, monkeypatch
    ) -> None:
        db_path = initialized_db

        from yoke_core.domain import migration_apply_targets as targets

        def fake_rollback_backup(target, reason, *, worktree_path):
            assert target.kind == "postgres"
            assert reason == "pre-migration-canonical-backup-sample"
            assert worktree_path == tmp_path
            path = worktree_path / ".yoke" / "backups" / "postgres.fake.sql"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("-- rollback dump\n", encoding="utf-8")
            return str(path)

        monkeypatch.setattr(
            targets, "create_rollback_backup", fake_rollback_backup,
        )

        returned_path = record_audit_fingerprint(
            db_path=db_path,
            name="canonical-backup-sample",
            description="exception-path with canonical rollback copy",
            tables=["items"],
            pre_counts={"items": 0},
            post_counts={"items": 0},
            backup_reason="canonical-backup-sample",
            exception_reason="decision record paired",
        )

        backup_dir = tmp_path / ".yoke" / "backups"
        assert returned_path.startswith(str(backup_dir) + os.sep), (
            f"backup file must land under canonical backups dir "
            f"({backup_dir}); got {returned_path!r}"
        )
        assert os.path.isfile(returned_path), (
            f"canonical backup file must exist on disk at {returned_path!r}"
        )
        canonical_re = re.compile(r"/\.yoke/backups/postgres\.fake\.sql$")
        assert canonical_re.search(returned_path), (
            f"backup filename must match canonical shape; got {returned_path!r}"
        )

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT backup_path FROM migration_audit "
                "WHERE migration_name = %s",
                ("canonical-backup-sample",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["backup_path"] == returned_path

    def test_empty_backup_reason_rejected(self, initialized_db: str) -> None:
        db_path = initialized_db
        with pytest.raises(ValueError) as excinfo:
            record_audit_fingerprint(
                db_path=db_path,
                name="empty-reason-rejected",
                description="empty string is ambiguous",
                tables=["items"],
                pre_counts={"items": 0},
                post_counts={"items": 0},
                backup_reason="",
            )
        assert "backup_reason" in str(excinfo.value)

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM migration_audit "
                "WHERE migration_name = %s",
                ("empty-reason-rejected",),
            ).fetchone()
        finally:
            conn.close()
        assert row["n"] == 0

    def test_none_backup_reason_requires_exception_reason(
        self, initialized_db: str
    ) -> None:
        db_path = initialized_db
        with pytest.raises(ValueError) as excinfo:
            record_audit_fingerprint(
                db_path=db_path,
                name="missing-no-backup-reason",
                description="no-backup branch without justification",
                tables=["items"],
                pre_counts={"items": 0},
                post_counts={"items": 0},
            )
        assert "exception_reason" in str(excinfo.value)

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM migration_audit "
                "WHERE migration_name = %s",
                ("missing-no-backup-reason",),
            ).fetchone()
        finally:
            conn.close()
        assert row["n"] == 0

    def test_backup_failure_raises_migration_backup_error(
        self, initialized_db: str
    ) -> None:
        db_path = initialized_db

        def _boom(db, reason):
            raise MigrationBackupError("simulated: disk full during .backup")

        with mock.patch(
            "yoke_core.domain.migration_harness.create_exception_backup",
            side_effect=_boom,
        ):
            with pytest.raises(MigrationBackupError) as excinfo:
                record_audit_fingerprint(
                    db_path=db_path,
                    name="backup-failure-sample",
                    description="exercise fail-closed contract",
                    tables=["items"],
                    pre_counts={"items": 0},
                    post_counts={"items": 0},
                    backup_reason="backup-failure-sample",
                )
        assert "disk full" in str(excinfo.value)

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM migration_audit "
                "WHERE migration_name = %s",
                ("backup-failure-sample",),
            ).fetchone()
        finally:
            conn.close()
        assert row["n"] == 0

    def test_create_exception_backup_rejects_empty_reason(
        self, initialized_db: str
    ) -> None:
        db_path = initialized_db
        with pytest.raises(ValueError):
            create_exception_backup(db_path, "")
        with pytest.raises(ValueError):
            create_exception_backup(db_path, "   ")

    def test_governed_migration_backup_fails_closed(self, initialized_db: str) -> None:
        with pytest.raises(MigrationBackupError) as excinfo:
            _run_backup(initialized_db, "pre-migration-retired")

        msg = str(excinfo.value)
        assert "yoke_core.domain.backup" in msg
        assert "migration_apply rehearse" in msg
        assert "migration_audit.backup_path" in msg

    def test_none_backup_reason_writes_empty_path(
        self, tmp_path: Path, initialized_db: str
    ) -> None:
        db_path = initialized_db
        returned = record_audit_fingerprint(
            db_path=db_path,
            name="no-backup-sample",
            description="retention-style call without rollback copy",
            tables=["items"],
            pre_counts={"items": 0},
            post_counts={"items": 0},
            exception_reason="bounded retention exception",
        )
        assert returned == ""

        conn = connect_test_db(db_path)
        try:
            row = conn.execute(
                "SELECT backup_path, exception_reason FROM migration_audit "
                "WHERE migration_name = %s",
                ("no-backup-sample",),
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row["backup_path"] == ""
        assert row["exception_reason"] == "bounded retention exception"
        assert not (tmp_path / "backups").exists()
