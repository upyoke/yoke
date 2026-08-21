"""Canonical launcher sweep: shim path, shadows, quarantine."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from yoke_core.tools import install_yoke_launcher_sweep as sweep
from yoke_core.tools.install_yoke_launcher_cleanup import quarantine_shadow_launcher
from yoke_core.tools.install_yoke_launcher_core import InstallError
from yoke_core.tools.install_yoke_launcher_sweep import (
    canonical_shim_path,
    classify_shadow,
    enumerate_shadow_installs,
    repair_canonical_launcher,
)


def _checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "pyproject.toml").write_text('name = "yoke"\n')
    return root


def _candidate_python(root: Path) -> Path:
    candidate = root / ".venv" / "bin" / "python3"
    candidate.parent.mkdir(parents=True)
    candidate.write_text("candidate interpreter\n")
    return candidate.absolute()


def _shim_interpreter(command: list[str]) -> Path:
    assert command[1:] == ["--version"]
    shebang = Path(command[0]).read_text().splitlines()[0]
    assert shebang.startswith("#!")
    return Path(shebang[2:])


def test_canonical_shim_path_uses_xdg_bin_home(tmp_path: Path) -> None:
    env = {"XDG_BIN_HOME": str(tmp_path / "bin")}
    assert canonical_shim_path(env) == tmp_path / "bin" / "yoke"


def test_enumerate_shadow_installs_skips_canonical(tmp_path: Path) -> None:
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "yoke").write_text("canon\n")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "yoke").write_text("shadow\n")
    env = {"PATH": f"{shadow_dir}:{canon}"}
    found = enumerate_shadow_installs(canonical=canon / "yoke", env=env)
    assert [s.path for s in found] == [shadow_dir / "yoke"]
    assert found[0].kind == classify_shadow(shadow_dir / "yoke")


def test_quarantine_shadow_launcher_never_deletes(tmp_path: Path) -> None:
    shadow = tmp_path / "yoke"
    shadow.write_text("old\n")
    dest = quarantine_shadow_launcher(shadow, stamp="1")
    assert dest.exists()
    assert not shadow.exists()
    assert "quarantine" in dest.name
    dest.replace(shadow)
    assert shadow.exists()


def test_repair_canonical_launcher_writes_shim(tmp_path: Path, monkeypatch) -> None:
    checkout = _checkout(tmp_path)
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    monkeypatch.setenv("XDG_BIN_HOME", str(target_dir))
    monkeypatch.setattr(
        sweep.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0),
    )
    written = repair_canonical_launcher(
        checkout,
        home=checkout,
        env={"XDG_BIN_HOME": str(target_dir)},
    )
    assert written == target_dir / "yoke"
    assert written.is_file()


def test_preferred_interpreter_failure_falls_back(tmp_path: Path, monkeypatch) -> None:
    checkout = _checkout(tmp_path)
    home = tmp_path / "home"
    preferred = _candidate_python(home)
    fallback = _candidate_python(checkout)
    target_dir = tmp_path / "bin"
    probed: list[Path] = []
    monkeypatch.setenv("YOKE_HOME", str(tmp_path / "conflicting-home"))
    monkeypatch.setenv("PYTHONHOME", str(tmp_path / "bad-python-home"))
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "bad-python-path"))

    def probe(command, **kwargs):
        assert kwargs["check"] is True
        assert kwargs["timeout"] == sweep.LAUNCHER_PROBE_TIMEOUT_SECONDS
        assert kwargs["env"]["YOKE_HOME"] == str(home)
        assert "PYTHONHOME" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        interpreter = _shim_interpreter(command)
        probed.append(interpreter)
        if interpreter == preferred:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sweep.subprocess, "run", probe)
    written = repair_canonical_launcher(
        checkout,
        home=home,
        env={"XDG_BIN_HOME": str(target_dir)},
    )

    assert probed == [preferred, fallback]
    assert written.read_text().splitlines()[0] == f"#!{fallback}"
    assert not list(target_dir.glob(".yoke.*.candidate"))


def test_dependency_poor_venv_is_rejected_by_real_launcher_probe(
    tmp_path: Path,
) -> None:
    checkout = _checkout(tmp_path)
    home = tmp_path / "isolated-home"
    subprocess.run(
        [sweep.sys.executable, "-m", "venv", str(home / ".venv")],
        check=True,
        capture_output=True,
        text=True,
    )
    target_dir = tmp_path / "bin"

    written = repair_canonical_launcher(
        checkout,
        home=home,
        env={"XDG_BIN_HOME": str(target_dir)},
    )

    assert written.read_text().splitlines()[0] == f"#!{sweep.sys.executable}"
    assert not list(target_dir.glob(".yoke.*.candidate"))


def test_all_probe_failures_preserve_regular_shim(tmp_path: Path, monkeypatch) -> None:
    checkout = _checkout(tmp_path)
    home = tmp_path / "home"
    _candidate_python(home)
    _candidate_python(checkout)
    current = tmp_path / "current-python"
    current.write_text("current interpreter\n")
    monkeypatch.setattr(sweep.sys, "executable", str(current))

    def fail_probe(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(sweep.subprocess, "run", fail_probe)
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    target = target_dir / "yoke"
    original = b"original canonical launcher bytes\n"
    target.write_bytes(original)
    original_inode = target.stat().st_ino

    with pytest.raises(InstallError, match="no candidate interpreter passed"):
        repair_canonical_launcher(
            checkout,
            home=home,
            force=True,
            env={"XDG_BIN_HOME": str(target_dir)},
        )

    assert target.read_bytes() == original
    assert target.stat().st_ino == original_inode
    assert not list(target_dir.glob(".yoke.*.candidate"))


def test_failed_repair_preserves_symlink_and_its_target(tmp_path: Path, monkeypatch) -> None:
    checkout = _checkout(tmp_path)
    home = tmp_path / "home"
    _candidate_python(home)
    current = tmp_path / "current-python"
    current.write_text("current interpreter\n")
    monkeypatch.setattr(sweep.sys, "executable", str(current))

    def time_out_probe(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(sweep.subprocess, "run", time_out_probe)
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    real = tmp_path / "real-yoke"
    real.write_text("KEEP\n")
    link = target_dir / "yoke"
    link.symlink_to(real)
    original_link = os.readlink(link)
    original_inode = link.lstat().st_ino

    with pytest.raises(InstallError, match="no candidate interpreter passed"):
        repair_canonical_launcher(
            checkout,
            home=home,
            env={"XDG_BIN_HOME": str(target_dir)},
        )

    assert link.is_symlink()
    assert os.readlink(link) == original_link
    assert link.lstat().st_ino == original_inode
    assert real.read_text() == "KEEP\n"
    assert not list(target_dir.glob(".yoke.*.candidate"))


def test_success_pins_shebang_and_atomically_replaces_symlink(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = _checkout(tmp_path)
    home = tmp_path / "home"
    base_interpreter = tmp_path / "base-python"
    base_interpreter.write_text("base interpreter\n")
    preferred = home / ".venv" / "bin" / "python3"
    preferred.parent.mkdir(parents=True)
    preferred.symlink_to(base_interpreter)
    preferred = preferred.absolute()
    assert preferred.resolve() == base_interpreter.resolve()
    monkeypatch.setattr(sweep.sys, "executable", str(base_interpreter))
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    real = tmp_path / "real-yoke"
    real.write_text("KEEP\n")
    link = target_dir / "yoke"
    link.symlink_to(real)
    probed: list[Path] = []

    def pass_only_venv_invocation(command, **kwargs):
        interpreter = _shim_interpreter(command)
        probed.append(interpreter)
        if interpreter != preferred:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(sweep.subprocess, "run", pass_only_venv_invocation)
    rendered: list[bytes] = []
    real_replace = sweep.os.replace

    def replace(source, destination) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        assert destination_path == link
        assert destination_path.is_symlink()
        assert source_path.parent == destination_path.parent
        rendered.append(source_path.read_bytes())
        real_replace(source_path, destination_path)

    monkeypatch.setattr(sweep.os, "replace", replace)
    written = repair_canonical_launcher(
        checkout,
        home=home,
        env={"XDG_BIN_HOME": str(target_dir)},
    )

    assert written == link
    assert written.is_file()
    assert not written.is_symlink()
    assert written.read_bytes() == rendered[0]
    assert written.read_text().splitlines()[0] == f"#!{preferred}"
    assert probed == [preferred]
    assert real.read_text() == "KEEP\n"


def test_converge_does_not_quarantine_shadows_when_repair_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    checkout = _checkout(tmp_path)
    current = tmp_path / "current-python"
    current.write_text("current interpreter\n")
    monkeypatch.setattr(sweep.sys, "executable", str(current))

    def fail_probe(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(sweep.subprocess, "run", fail_probe)
    quarantined: list[Path] = []

    def quarantine(path, **kwargs):
        quarantined.append(path)
        return path

    monkeypatch.setattr(sweep, "quarantine_shadow_launcher", quarantine)
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    canonical = target_dir / "yoke"
    canonical.write_text("original canonical launcher\n")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    shadow = shadow_dir / "yoke"
    shadow.write_text("shadow launcher\n")

    with pytest.raises(InstallError, match="no candidate interpreter passed"):
        sweep.converge_machine(
            checkout,
            force=True,
            env={
                "PATH": str(shadow_dir),
                "XDG_BIN_HOME": str(target_dir),
            },
        )

    assert canonical.read_text() == "original canonical launcher\n"
    assert shadow.read_text() == "shadow launcher\n"
    assert quarantined == []
