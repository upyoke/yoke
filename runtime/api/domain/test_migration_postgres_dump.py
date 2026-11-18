"""Postgres restore points use the shared client resolver safely."""

from __future__ import annotations

import os
import subprocess
import stat
from pathlib import Path

import pytest

from yoke_contracts.owner_private_path import (
    create_owner_private_directory,
    is_owner_private_directory,
    is_owner_private_file,
)
from yoke_core.domain import (
    migration_apply_targets,
    postgres_client_runtime,
    postgres_dump_restore_point,
)

EXE = ".exe" if os.name == "nt" else ""


def test_shared_resolver_prefers_installed_engine_then_falls_back_to_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bin_dir = tmp_path / "postgres-17" / "bin"
    monkeypatch.delenv(postgres_client_runtime.postgres_binaries.BIN_DIR_ENV, raising=False)
    monkeypatch.setattr(
        postgres_client_runtime.postgres_binaries,
        "installed_bin_dir",
        lambda: bin_dir,
    )

    assert postgres_client_runtime.postgres_executable("pg_dump") == str(
        bin_dir / f"pg_dump{EXE}"
    )

    monkeypatch.setattr(
        postgres_client_runtime.postgres_binaries,
        "installed_bin_dir",
        lambda: None,
    )
    assert postgres_client_runtime.postgres_executable("pg_dump") == f"pg_dump{EXE}"


def _publish_restore_point(
    backup_dir: Path,
    monkeypatch,
    selected: str,
    dsn: str,
) -> tuple[Path, dict[str, object]]:
    """Run one fake pg_dump and record argv, privacy and fsync evidence."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        postgres_client_runtime,
        "postgres_executable",
        lambda name: selected if name == "pg_dump" else name,
    )

    def run(argv, **kwargs):
        seen.update(argv=argv, env=kwargs["env"])
        output = kwargs["stdout"]
        candidates = list(backup_dir.glob(".*.sql.partial"))
        assert len(candidates) == 1
        destination = candidates[0]
        seen["partial"] = destination
        assert destination.name.startswith(".postgres.")
        assert destination.name.endswith(".sql.partial")
        seen["partial_mode"] = stat.S_IMODE(destination.stat().st_mode)
        seen["partial_private"] = is_owner_private_file(destination)
        seen["parent_private"] = is_owner_private_directory(destination.parent)
        output.write(b"-- safe restore point\n")
        output.flush()
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    real_replace = postgres_dump_restore_point.os.replace
    real_fsync = postgres_dump_restore_point.os.fsync
    real_sync = postgres_dump_restore_point.platform_file_sync.sync_directory

    def replace(source, destination):
        seen.update(
            replace_source=Path(source),
            replace_destination=Path(destination),
        )
        real_replace(source, destination)

    def sync_directory(path):
        seen["synced_directory"] = path
        real_sync(path)

    def fsync(descriptor):
        seen.setdefault("fsync_modes", []).append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(postgres_dump_restore_point.subprocess, "run", run)
    monkeypatch.setattr(postgres_dump_restore_point.os, "replace", replace)
    monkeypatch.setattr(postgres_dump_restore_point.os, "fsync", fsync)
    monkeypatch.setattr(
        postgres_dump_restore_point.platform_file_sync, "sync_directory", sync_directory
    )

    backup = migration_apply_targets.dump_postgres_to_directory(
        dsn,
        "pre-apply",
        backup_dir,
    )
    return Path(backup), seen


def test_restore_point_uses_selected_binary_and_keeps_dsn_out_of_argv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = str(tmp_path / "postgres-17" / "bin" / "pg_dump")
    dsn = "postgresql://operator:dump-secret@db.example/app"
    backup_dir = tmp_path / "backups"

    backup_path, seen = _publish_restore_point(backup_dir, monkeypatch, selected, dsn)

    argv = seen["argv"]
    env = seen["env"]
    assert isinstance(argv, list)
    assert isinstance(env, dict)
    assert argv[0] == selected
    assert dsn not in argv
    assert all("dump-secret" not in argument for argument in argv)
    assert env["PGPASSWORD"] == "dump-secret"
    assert "--file" not in argv
    assert seen["partial_private"] is True
    assert seen["parent_private"] is True
    assert backup_path == seen["replace_destination"]
    assert seen["partial"] == seen["replace_source"]
    assert not Path(seen["partial"]).exists()
    assert backup_path.read_text(encoding="utf-8") == "-- safe restore point\n"
    assert is_owner_private_file(backup_path)
    assert is_owner_private_directory(backup_dir)
    assert any(stat.S_ISREG(mode) for mode in seen["fsync_modes"])
    assert seen["synced_directory"] == backup_dir


@pytest.mark.posix_only(reason="POSIX mode bits: an existing 0755 folder is tightened")
def test_restore_point_tightens_existing_folder_and_fsyncs_it(
    tmp_path: Path,
    monkeypatch,
) -> None:
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o755)
    backup_dir.chmod(0o755)

    backup_path, seen = _publish_restore_point(
        backup_dir, monkeypatch, "pg_dump", "postgresql://operator@db.example/app"
    )

    assert seen["partial_mode"] == 0o600
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert seen["synced_directory"] == backup_dir
    assert any(stat.S_ISDIR(mode) for mode in seen["fsync_modes"])


@pytest.mark.windows_only(reason="native Windows DACL: icacls grants Users folder access")
def test_restore_point_refuses_existing_folder_other_users_can_open(
    tmp_path: Path,
) -> None:
    backup_dir = create_owner_private_directory(tmp_path / "backups")
    subprocess.run(
        ["icacls", str(backup_dir), "/grant", "*S-1-5-32-545:(OI)(CI)(R)"],
        check=True,
        capture_output=True,
    )

    with pytest.raises(RuntimeError, match="not owner-private.*icacls"):
        migration_apply_targets.dump_postgres_to_directory(
            "postgresql://operator@db.example/app", "pre-apply", backup_dir
        )

    assert list(backup_dir.iterdir()) == []


def test_version_mismatch_is_actionable_and_redacts_connection_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = str(tmp_path / "postgres-16" / "bin" / "pg_dump")
    dsn = "postgresql://operator:dump-secret@db.example/app"
    monkeypatch.setattr(
        postgres_client_runtime,
        "postgres_executable",
        lambda _name: selected,
    )

    def mismatch(argv, **kwargs):
        output = kwargs["stdout"]
        output.write(b"partial")
        output.flush()
        return subprocess.CompletedProcess(
            argv,
            1,
            stdout="",
            stderr=(
                "pg_dump: error: aborting because of server version mismatch\n"
                "pg_dump: detail: server version: 17.10; "
                "pg_dump version: 16.14\n"
                f"connection={dsn} password=dump-secret"
            ),
        )

    monkeypatch.setattr(postgres_dump_restore_point.subprocess, "run", mismatch)

    with pytest.raises(RuntimeError) as excinfo:
        migration_apply_targets.dump_postgres_to_directory(
            dsn,
            "pre-apply",
            tmp_path / "backups",
        )

    message = str(excinfo.value)
    assert selected in message
    assert "server version: 17.10" in message
    assert "pg_dump version: 16.14" in message
    assert "major version is at least" in message
    assert "dump-secret" not in message
    assert dsn not in message
    assert "<redacted-secret>" in message
    assert list((tmp_path / "backups").iterdir()) == []
