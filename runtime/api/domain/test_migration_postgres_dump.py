"""Postgres restore points use the shared client resolver safely."""

from __future__ import annotations

import os
import subprocess
import stat
from pathlib import Path

import pytest

from yoke_core.domain import (
    migration_apply_targets,
    postgres_client_runtime,
    postgres_dump_restore_point,
)


def test_shared_resolver_prefers_installed_engine_then_falls_back_to_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    bin_dir = tmp_path / "postgres-17" / "bin"
    monkeypatch.setattr(
        postgres_client_runtime.postgres_binaries,
        "installed_bin_dir",
        lambda: bin_dir,
    )

    assert postgres_client_runtime.postgres_executable("pg_dump") == str(
        bin_dir / "pg_dump"
    )

    monkeypatch.setattr(
        postgres_client_runtime.postgres_binaries,
        "installed_bin_dir",
        lambda: None,
    )
    assert postgres_client_runtime.postgres_executable("pg_dump") == "pg_dump"


def test_restore_point_uses_selected_binary_and_keeps_dsn_out_of_argv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = str(tmp_path / "postgres-17" / "bin" / "pg_dump")
    dsn = "postgresql://operator:dump-secret@db.example/app"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o755)
    backup_dir.chmod(0o755)
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
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
        assert stat.S_IMODE(destination.parent.stat().st_mode) == 0o700
        output.write(b"-- safe restore point\n")
        output.flush()
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    real_replace = postgres_dump_restore_point.os.replace
    real_fsync = postgres_dump_restore_point.os.fsync

    def replace(source, destination):
        seen.update(
            replace_source=Path(source),
            replace_destination=Path(destination),
        )
        real_replace(source, destination)

    def fsync(descriptor):
        seen.setdefault("fsync_modes", []).append(os.fstat(descriptor).st_mode)
        real_fsync(descriptor)

    monkeypatch.setattr(postgres_dump_restore_point.subprocess, "run", run)
    monkeypatch.setattr(postgres_dump_restore_point.os, "replace", replace)
    monkeypatch.setattr(postgres_dump_restore_point.os, "fsync", fsync)

    backup = migration_apply_targets.dump_postgres_to_directory(
        dsn,
        "pre-apply",
        backup_dir,
    )

    argv = seen["argv"]
    env = seen["env"]
    assert isinstance(argv, list)
    assert isinstance(env, dict)
    assert argv[0] == selected
    assert dsn not in argv
    assert all("dump-secret" not in argument for argument in argv)
    assert env["PGPASSWORD"] == "dump-secret"
    assert "--file" not in argv
    backup_path = Path(backup)
    assert backup_path == seen["replace_destination"]
    assert seen["partial"] == seen["replace_source"]
    assert not Path(seen["partial"]).exists()
    assert backup_path.read_text(encoding="utf-8") == "-- safe restore point\n"
    assert stat.S_IMODE(backup_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert any(stat.S_ISREG(mode) for mode in seen["fsync_modes"])
    assert any(stat.S_ISDIR(mode) for mode in seen["fsync_modes"])


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
