"""Canonical launcher sweep: shim path, shadows, quarantine."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools.install_yoke_launcher_cleanup import quarantine_shadow_launcher
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
    written = repair_canonical_launcher(checkout, home=checkout, env={"XDG_BIN_HOME": str(target_dir)})
    assert written == target_dir / "yoke"
    assert written.is_file()


def test_repair_replaces_symlink_without_clobbering_target(tmp_path: Path, monkeypatch) -> None:
    checkout = _checkout(tmp_path)
    target_dir = tmp_path / "bin"
    target_dir.mkdir()
    real = tmp_path / "real-yoke"
    real.write_text("KEEP\n")
    link = target_dir / "yoke"
    link.symlink_to(real)
    monkeypatch.setenv("XDG_BIN_HOME", str(target_dir))
    written = repair_canonical_launcher(
        checkout, home=checkout, env={"XDG_BIN_HOME": str(target_dir)},
    )
    assert written == link
    assert written.is_file()
    assert not written.is_symlink()
    assert real.read_text() == "KEEP\n"
