"""Standalone Postgres clients resolve the pinned engine, not an older PATH one."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import postgres_binaries, postgres_client_runtime
from yoke_core.tools.source_postgres_environment import shared_postgres_environment


def _client_dir(root: Path, *names: str) -> Path:
    root.mkdir(parents=True)
    for name in names:
        (root / name).write_text("#!/bin/sh\n")
        (root / name).chmod(0o755)
    return root


def test_source_run_with_older_path_client_resolves_the_bundled_one(
    tmp_path, monkeypatch,
):
    real_home = tmp_path / "real" / ".yoke"
    bundled = _client_dir(
        real_home / "postgres" / postgres_binaries.POSTGRES_VERSION / "bin",
        "initdb", "pg_dump",
    )
    older = _client_dir(tmp_path / "homebrew" / "bin", "pg_dump")
    for key in ("YOKE_PG_BIN_DIR", "YOKE_PG_CLUSTER_ROOT"):
        monkeypatch.delenv(key, raising=False)
    source_env = shared_postgres_environment(
        {"YOKE_MACHINE_HOME": str(real_home), "YOKE_SCRATCH_ROOT": str(tmp_path)}
    )
    # Source isolation then swaps in a disposable home with no fetched engine.
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "disposable"))
    monkeypatch.setenv("YOKE_PG_BIN_DIR", source_env["YOKE_PG_BIN_DIR"])
    monkeypatch.setenv("PATH", str(older))

    assert postgres_binaries.installed_bin_dir() is None
    assert postgres_client_runtime.postgres_executable("pg_dump") == str(
        bundled / "pg_dump"
    )


def test_installed_engine_is_used_without_an_override(tmp_path, monkeypatch):
    monkeypatch.delenv("YOKE_PG_BIN_DIR", raising=False)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))
    bundled = _client_dir(
        tmp_path / "postgres" / postgres_binaries.POSTGRES_VERSION / "bin",
        "initdb", "pg_dump",
    )

    assert postgres_client_runtime.postgres_executable("pg_dump") == str(
        bundled / "pg_dump"
    )


def test_no_pinned_engine_uses_path(tmp_path, monkeypatch):
    monkeypatch.delenv("YOKE_PG_BIN_DIR", raising=False)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path))

    assert postgres_client_runtime.postgres_executable("pg_dump") == "pg_dump"
