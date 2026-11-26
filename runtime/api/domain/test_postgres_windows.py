"""Native Windows engine resolution and helper process regressions."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import subprocess
import sys
import tarfile

import pytest

from yoke_contracts.owner_private_path import is_owner_private_directory
from yoke_contracts.platform_fs import extended_length_path, remove_tree
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


def test_missing_dll_hint_names_vc_runtime_first(monkeypatch):
    monkeypatch.setattr(
        postgres_cluster_process.terminal_detached_process,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0xC0000135),
    )
    stderr = postgres_cluster_process._run(["initdb"]).stderr
    assert "embedded_postgres_load_failed" in stderr
    runtime = stderr.index("vcruntime140.dll, vcruntime140_1.dll, msvcp140.dll")
    repair = stderr.index("yoke local-postgres start")
    assert runtime < repair < stderr.index("owner access")


def test_windows_archive_directories_use_owner_private_creation(monkeypatch, tmp_path):
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


@pytest.mark.windows_only(reason="requires native Windows extended paths and directory ACLs")
@pytest.mark.parametrize("deep_home", [False, True], ids=["short-home", "deep-home"])
def test_fetch_postgres_on_windows_paths(monkeypatch, tmp_path, deep_home):
    home = tmp_path / "home"
    if deep_home:
        home = home / ("profile-" + "x" * 145)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    # The test exercises the engine archive only and makes no runtime downloads.
    monkeypatch.setattr(
        postgres_binaries.windows_vc_runtime_install, "ensure_runtime",
        lambda *_args, **_kwargs: None,
    )
    version, target = "9.9.9", "x86_64-pc-windows-msvc"
    releases = tmp_path / "releases"
    release = releases / version
    release.mkdir(parents=True)
    archive = release / postgres_binaries.release_asset_name(version, target)
    top = archive.name.removesuffix(".tar.gz")
    directory_name = "share/tsearch_data"
    filename = f"extension-{'x' * 85}.sql" if deep_home else "extension.sql"
    member = f"{directory_name}/{filename}"
    payload = b"select 1;"
    directory_mtime = 1_600_000_000
    with tarfile.open(archive, "w:gz") as stream:
        for name in (top, f"{top}/bin", f"{top}/share", f"{top}/{directory_name}"):
            directory = tarfile.TarInfo(name)
            directory.type = tarfile.DIRTYPE
            directory.mtime = directory_mtime
            stream.addfile(directory)
        for name in ("bin/initdb.exe", member):
            entry = tarfile.TarInfo(f"{top}/{name}")
            entry.size = len(payload)
            stream.addfile(entry, io.BytesIO(payload))
    archive.with_suffix(".gz.sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest(), encoding="ascii",
    )

    # Hosted runners can opt into long paths. Assert the path at the write
    # boundary so a regression fails even there, without changing host policy.
    original_makefile = tarfile.TarFile.makefile
    original_utime = tarfile.TarFile.utime
    extended_prefix = "\\\\?\\"
    metadata_targets = []

    def check_write(stream, entry, targetpath):
        if entry.name == f"{top}/{member}":
            assert (len(targetpath.removeprefix(extended_prefix)) >= 260) == deep_home
            assert targetpath.startswith(extended_prefix)
        return original_makefile(stream, entry, targetpath)

    def check_utime(stream, entry, targetpath):
        if entry.isdir() and entry.name.endswith("tsearch_data"):
            assert targetpath.startswith(extended_prefix)
            assert "/" not in targetpath
            metadata_targets.append(targetpath)
        return original_utime(stream, entry, targetpath)

    monkeypatch.setattr(tarfile.TarFile, "makefile", check_write)
    monkeypatch.setattr(tarfile.TarFile, "utime", check_utime)
    dest = postgres_binaries.version_dir(version)
    installed = Path(extended_length_path(dest / member))
    binaries_root = Path(extended_length_path(dest.parent))
    assert (len(str(dest / member)) >= 260) == deep_home
    try:
        for _ in range(2):
            assert postgres_binaries.fetch_binaries(
                version, target, base_url=releases.as_uri(),
            ) == dest / "bin"
            assert installed.read_bytes() == payload
            assert is_owner_private_directory(installed.parent)
            assert installed.parent.stat().st_mtime == directory_mtime
            assert list(binaries_root.glob(".fetch-*")) == []
            # A second promotion must remove the old tree.
            installed.write_bytes(b"stale")
        assert len(metadata_targets) == 2
    finally:
        remove_tree(extended_length_path(home))


def test_windows_tar_filter_rejects_directory_outside_destination(tmp_path):
    directory = tarfile.TarInfo("../outside")
    directory.type = tarfile.DIRTYPE
    with pytest.raises(tarfile.OutsideDestinationError):
        postgres_binaries._windows_tar_filter(directory, str(tmp_path))
