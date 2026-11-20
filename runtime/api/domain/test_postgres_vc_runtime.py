"""The Windows engine gets its MSVC runtime DLLs app-local, without elevation."""

from __future__ import annotations

import hashlib
import ntpath
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts import windows_vc_runtime as runtime
from yoke_contracts import windows_vc_runtime_install as installer
from yoke_core.domain import local_universe
from yoke_core.domain import postgres_binaries
from yoke_core.domain import postgres_cluster

pytestmark = pytest.mark.windows

SYSTEM_ROOT = "D:\\Win"
ENV = {"SystemRoot": SYSTEM_ROOT}


def _dll(name: str) -> bytes:
    return f"redistributable copy of {name}".encode()


@pytest.fixture
def redist(monkeypatch, tmp_path):
    """A fake pinned redistributable and inbox tar.exe; returns what they saw."""
    seen = SimpleNamespace(fetches=[], tar=[], system32=set())
    monkeypatch.setattr(installer, "_WINDOWS", True)
    monkeypatch.setenv("SystemRoot", SYSTEM_ROOT)
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(
        runtime,
        "RUNTIME_DLLS",
        {name: hashlib.sha256(_dll(name)).hexdigest() for name in runtime.RUNTIME_DLLS},
    )
    body = b"\0" * runtime.CONTAINER_OFFSET + b"MSCF" + b"\0" * (runtime.CONTAINER_SIZE - 4)

    def fetch_bytes(url, **kwargs):
        seen.fetches.append((url, kwargs["expected_sha256"]))
        return SimpleNamespace(body=body)

    def run(argv, **kwargs):
        seen.tar.append(argv)
        dest = Path(argv[argv.index("-C") + 1])
        for member in argv[argv.index("-C") + 2:]:
            name = member.removesuffix(runtime.MEMBER_SUFFIX)
            (dest / member).write_bytes(_dll(name) if name in runtime.RUNTIME_DLLS else b"cab")
        return subprocess.CompletedProcess(argv, 0, "", "")

    real_isfile = runtime.os.path.isfile
    monkeypatch.setattr(installer, "fetch_bytes", fetch_bytes)
    monkeypatch.setattr(installer.subprocess, "run", run)
    monkeypatch.setattr(
        runtime.os.path,
        "isfile",
        lambda path: str(path) in seen.system32 or real_isfile(path),
    )
    return seen


def _bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "engine" / "bin"
    bin_dir.mkdir(parents=True)
    return bin_dir


def test_install_copies_only_missing_dlls_from_the_pinned_redist(redist, tmp_path):
    bin_dir = _bin(tmp_path)
    (bin_dir / "vcruntime140.dll").write_bytes(b"already in bin")
    redist.system32.add(ntpath.join(SYSTEM_ROOT, "System32", "vcruntime140_1.dll"))

    assert installer.ensure_runtime(bin_dir) == ["msvcp140.dll"]

    assert (bin_dir / "msvcp140.dll").read_bytes() == _dll("msvcp140.dll")
    assert (bin_dir / "vcruntime140.dll").read_bytes() == b"already in bin"
    assert not (bin_dir / "vcruntime140_1.dll").exists()
    assert redist.fetches == [(runtime.REDIST_URL, runtime.REDIST_SHA256)]
    tar = ntpath.join(SYSTEM_ROOT, "System32", "tar.exe")
    assert [argv[0] for argv in redist.tar] == [tar, tar]
    assert redist.tar[0][-1] == runtime.RUNTIME_CABINET
    assert redist.tar[1][-1] == "msvcp140.dll" + runtime.MEMBER_SUFFIX
    assert sorted(p.name for p in bin_dir.parent.iterdir()) == ["bin"]


def test_nothing_is_fetched_when_every_dll_is_present(redist, tmp_path):
    bin_dir = _bin(tmp_path)
    for name in runtime.RUNTIME_DLLS:
        redist.system32.add(ntpath.join(SYSTEM_ROOT, "System32", name))
    assert installer.ensure_runtime(bin_dir) == []
    assert redist.fetches == [] and list(bin_dir.iterdir()) == []


def test_a_tampered_dll_is_refused_and_never_lands_in_bin(redist, tmp_path, monkeypatch):
    monkeypatch.setitem(runtime.RUNTIME_DLLS, "msvcp140.dll", "0" * 64)
    bin_dir = _bin(tmp_path)
    with pytest.raises(installer.VcRuntimeError) as raised:
        installer.ensure_runtime(bin_dir)
    message = str(raised.value)
    assert message.startswith("embedded_postgres_vc_runtime_unavailable")
    assert "msvcp140.dll from the redistributable failed its sha256 check" in message
    assert "winget install --id Microsoft.VCRedist.2015+.x64 -e" in message
    assert list(bin_dir.iterdir()) == []
    assert sorted(p.name for p in bin_dir.parent.iterdir()) == ["bin"]


def test_engine_fetch_installs_the_runtime_into_bin(redist, tmp_path, monkeypatch):
    from runtime.api.domain.test_postgres_binaries import _fixture_release

    base_url = _fixture_release(tmp_path / "releases", "9.9.9", "aarch64-apple-darwin")
    bin_dir = postgres_binaries.fetch_binaries(
        "9.9.9", "aarch64-apple-darwin", base_url=base_url
    )
    assert sorted(p.name for p in bin_dir.glob("*.dll")) == sorted(runtime.RUNTIME_DLLS)


def test_start_repairs_an_engine_installed_without_the_runtime(
    redist, tmp_path, monkeypatch
):
    bin_dir = _bin(tmp_path)
    spec = local_universe.cluster_spec(root=tmp_path / "universe", bin_dir=bin_dir)
    monkeypatch.setattr(postgres_cluster, "start_failure", lambda _spec: None)
    monkeypatch.setattr(local_universe, "ensure_database", lambda _spec: None)
    monkeypatch.setattr(local_universe, "status", lambda _spec: {"running": True})

    assert local_universe.start(spec) == {"running": True}
    assert sorted(p.name for p in bin_dir.iterdir()) == sorted(runtime.RUNTIME_DLLS)
