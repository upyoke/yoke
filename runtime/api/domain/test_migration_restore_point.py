"""Restore-point dumps use the caller's explicit database authority."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import migration_apply_targets, migration_restore_point


class _PostgresConnection:
    pass


def test_backup_root_refuses_without_an_explicit_dump_target(tmp_path: Path) -> None:
    with pytest.raises(
        migration_restore_point.RestorePointRequired,
        match="backup_target_dsn",
    ):
        migration_restore_point.establish(
            _PostgresConnection(),
            backup_root=tmp_path,
            external_restore_point=None,
        )


def test_blank_external_restore_point_is_refused() -> None:
    with pytest.raises(
        migration_restore_point.RestorePointRequired,
        match="non-empty identifier",
    ):
        migration_restore_point.establish(
            _PostgresConnection(),
            backup_root=None,
            external_restore_point="   ",
        )


def test_dump_uses_the_caller_resolved_target_not_ambient_authority(
    tmp_path: Path, monkeypatch,
) -> None:
    seen = {}

    def dump(dsn: str, reason: str, backup_root: Path) -> str:
        seen.update(dsn=dsn, reason=reason, backup_root=backup_root)
        return "backup:external-project"

    monkeypatch.setattr(migration_apply_targets, "dump_postgres_to_directory", dump)

    restore_point = migration_restore_point.establish(
        _PostgresConnection(),
        backup_root=tmp_path,
        backup_target_dsn="postgresql://external.example/external_app",
        external_restore_point=None,
    )

    assert restore_point == "backup:external-project"
    assert seen == {
        "dsn": "postgresql://external.example/external_app",
        "reason": migration_restore_point.BACKUP_REASON,
        "backup_root": tmp_path,
    }
