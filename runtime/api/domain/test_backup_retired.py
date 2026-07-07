"""Regression coverage for the retired ``yoke.db`` backup command."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from yoke_core.domain import backup


def test_create_backup_is_retired_without_creating_destination(tmp_path: Path) -> None:
    backup_dir = tmp_path / "data" / "backups"

    with pytest.raises(backup.RetiredBackupError, match="SQLite yoke.db"):
        backup.create_backup(
            str(tmp_path / "data" / "yoke.db"),
            str(backup_dir),
            "manual",
        )

    assert not backup_dir.exists()


def test_cli_backup_fails_without_resolving_db_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_resolve() -> str:
        raise AssertionError("retired backup CLI must not resolve a DB path")

    monkeypatch.setattr(backup.db_helpers, "resolve_db_path", fail_resolve)

    with pytest.raises(SystemExit) as exc:
        backup.main(["backup", "manual", "--backup-dir", str(tmp_path / "backups")])

    assert exc.value.code == 1
    assert "SQLite yoke.db file backups are retired" in capsys.readouterr().err


def test_periodic_fails_without_requiring_data_yoke_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc:
        backup.main(["periodic"])

    assert exc.value.code == 1
    assert "SQLite yoke.db file backups are retired" in capsys.readouterr().err
    assert not (tmp_path / "data" / "yoke.db").exists()


def test_no_sqlite_subprocess_surface_remains() -> None:
    source = Path(backup.__file__).read_text()

    assert "import subprocess" not in source
    assert '"sqlite3"' not in source
    assert "'.backup" not in source
    assert ".backup" not in source
    assert importlib.util.find_spec("yoke_core.domain.backup_s3") is None


def test_residue_list_latest_and_prune_still_work(tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "yoke.db.20260101-000000.old.sqlite3"
    new = backup_dir / "yoke.db.20260102-000000.new.sqlite3"
    other = backup_dir / "postgres.20260103-000000.new.sql"
    old.write_text("old", encoding="utf-8")
    new.write_text("new", encoding="utf-8")
    other.write_text("other", encoding="utf-8")

    assert backup.list_backups(str(backup_dir)) == [str(new), str(old)]
    assert backup.newest_backup(str(backup_dir)) == str(new)

    assert backup.prune_backups(str(backup_dir), 1) == 1
    assert new.exists()
    assert not old.exists()
    assert other.exists()
