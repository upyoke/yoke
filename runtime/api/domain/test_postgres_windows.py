"""Native Windows engine resolution and helper process regressions."""
from __future__ import annotations

import pytest

import subprocess
import sys

from yoke_core.domain import postgres_binaries, postgres_cluster_process


pytestmark = pytest.mark.windows


def test_windows_executables_and_installed_engine(monkeypatch, tmp_path):
    monkeypatch.setattr(postgres_cluster_process, "_WINDOWS", True)
    monkeypatch.setattr(postgres_binaries, "_WINDOWS", True)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "profile with spaces"))
    binary = postgres_binaries.version_dir() / "bin"
    binary.mkdir(parents=True)
    (binary / "initdb.exe").touch()
    assert postgres_binaries.installed_bin_dir() == binary
    assert postgres_cluster_process.executable(binary, "initdb") == str(binary / "initdb.exe")
    assert postgres_cluster_process.executable(None, "pg_ctl") == "pg_ctl.exe"


def test_helper_does_not_wait_for_grandchild_to_close_output(tmp_path):
    release = tmp_path / "release-child"
    child = (
        "import pathlib,time; "
        f"p=pathlib.Path({str(release)!r}); "
        "deadline=time.monotonic()+10; "
        "exec('while not p.exists() and time.monotonic()<deadline: time.sleep(.02)')"
    )
    script = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('helper exited')"
    )
    try:
        result = postgres_cluster_process._run([sys.executable, "-c", script], timeout=3)
        assert result.returncode == 0
        assert result.stdout.strip() == "helper exited"
    finally:
        release.touch()


def test_helper_timeout_names_recovery(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 0.1)
    monkeypatch.setattr(postgres_cluster_process.terminal_detached_process, "run", timeout)
    result = postgres_cluster_process._run(["pg_ctl", "start"])
    assert result.returncode != 0
    assert "postgres_process_timeout" in result.stderr
    assert "server.log" in result.stderr


def test_windows_archive_directories_use_owner_private_creation(monkeypatch, tmp_path):
    import tarfile
    from pathlib import Path
    payload = tmp_path / "payload"
    (payload / "bin").mkdir(parents=True)
    (payload / "bin" / "initdb.exe").touch()
    archive = tmp_path / "engine.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(payload, arcname="postgresql")
    created = []
    real_create = postgres_binaries.create_owner_private_directory
    def create(path):
        created.append(Path(path).name)
        return real_create(path)
    monkeypatch.setattr(postgres_binaries, "_WINDOWS", True)
    monkeypatch.setattr(postgres_binaries, "create_owner_private_directory", create)
    staging = tmp_path / "staging"
    staging.mkdir()
    dest = tmp_path / "installed"
    postgres_binaries._unpack_release(archive, staging, dest)
    assert (dest / "bin" / "initdb.exe").is_file()
    assert {"extracted", "postgresql", "bin"} <= set(created)
