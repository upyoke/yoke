"""Pytest config isolation preserves installed local executable access."""

import os
from pathlib import Path
import shutil

from yoke_core.domain import postgres_binaries
from yoke_core.tools import _pytest_parallel, pg_testcluster


def test_embedded_executables_remain_available_after_machine_home_isolation(
    tmp_path, monkeypatch
):
    home = tmp_path / "machine"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    binaries = postgres_binaries.version_dir() / "bin"
    binaries.mkdir(parents=True)
    for name in ("initdb", "pg_isready"):
        executable = binaries / name
        executable.touch()
        executable.chmod(0o700)
    original = {"YOKE_MACHINE_HOME": str(home), "PATH": os.defpath}

    isolated = _pytest_parallel.isolate_from_administering_machine_config(original)

    assert isolated["YOKE_MACHINE_HOME"] != str(home)
    assert original["PATH"] == os.defpath
    with monkeypatch.context() as child:
        child.setenv("YOKE_MACHINE_HOME", isolated["YOKE_MACHINE_HOME"])
        child.setenv("PATH", isolated["PATH"])
        assert pg_testcluster._spec().bin_dir is None
        assert shutil.which("pg_isready") == str(binaries / "pg_isready")


def test_without_embedded_binaries_isolation_preserves_system_path(monkeypatch):
    monkeypatch.setattr(postgres_binaries, "installed_bin_dir", lambda: None)
    env = {"PATH": "/system/bin"}

    isolated = _pytest_parallel.isolate_from_administering_machine_config(env)

    assert isolated["PATH"] == env["PATH"]
    assert Path(isolated["YOKE_MACHINE_HOME"]).is_dir()
