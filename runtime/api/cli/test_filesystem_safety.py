"""Tests for shared symlink-component and atomic-file safety helpers."""

import stat
from pathlib import Path

import pytest

from yoke_cli import filesystem_safety


def test_atomic_replace_cleans_unique_temporary_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "settings.json"

    def refuse_replace(_source, _target):
        raise OSError("injected replace failure")

    monkeypatch.setattr(filesystem_safety.os, "replace", refuse_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        filesystem_safety.atomic_replace_bytes(target, b"payload\n")

    assert list(tmp_path.glob(".settings.json.*.tmp")) == []
    assert not target.exists()


def test_first_symlink_component_can_exclude_materializable_leaf(
    tmp_path: Path,
) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    leaf = tmp_path / "leaf"
    leaf.symlink_to(real_parent)

    assert filesystem_safety.first_symlink_component(tmp_path, leaf) is None
    assert filesystem_safety.first_symlink_component(
        tmp_path, leaf, include_leaf=True,
    ) == leaf


def test_atomic_replace_preserves_existing_private_file_mode(
    tmp_path: Path,
) -> None:
    target = tmp_path / "settings.json"
    target.write_bytes(b"old\n")
    target.chmod(0o600)

    filesystem_safety.atomic_replace_bytes(target, b"new\n")

    assert target.read_bytes() == b"new\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
