"""Owner-private file checks select the platform permission model."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_contracts import owner_private_path


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits do not model DACLs")
def test_posix_owner_private_file_requires_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    path.chmod(0o600)

    assert owner_private_path.is_owner_private_file(path) is True

    path.chmod(0o640)
    assert owner_private_path.is_owner_private_file(path) is False


def test_windows_owner_private_file_uses_dacl_validator(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    checked: list[Path] = []
    monkeypatch.setattr(owner_private_path, "_WINDOWS_PERMISSIONS", True)
    monkeypatch.setattr(
        owner_private_path.windows_private_directory,
        "is_private_file",
        lambda selected: checked.append(selected) or True,
    )

    assert owner_private_path.is_owner_private_file(path) is True
    assert checked == [path]


def test_owner_private_path_exports_only_file_validator() -> None:
    assert {"is_owner_private_file", "is_owner_private_directory",
            "create_owner_private_directory", "write_owner_private"} == set(owner_private_path.__all__)


@pytest.mark.parametrize("data", ["héllo", b"secret"])
def test_atomic_private_write(data, tmp_path):
    path = tmp_path / "secret"
    owner_private_path.write_owner_private(path, data)
    assert path.read_bytes() == (data.encode("utf-8") if isinstance(data, str) else data)
    assert owner_private_path.is_owner_private_file(path)
    owner_private_path.write_owner_private(path, b"replacement")
    assert path.read_bytes() == b"replacement"
    assert list(tmp_path.iterdir()) == [path]


def test_private_write_replace_failure_preserves_old_data(monkeypatch, tmp_path):
    path = tmp_path / "secret"
    owner_private_path.write_owner_private(path, b"before")
    def fail(*args):
        raise PermissionError("locked")
    monkeypatch.setattr(owner_private_path.os, "replace", fail)
    with pytest.raises(OSError, match="owner_private_write_failed"):
        owner_private_path.write_owner_private(path, b"after")
    assert path.read_bytes() == b"before"
    assert list(tmp_path.iterdir()) == [path]


def test_private_directory_creation_and_existing_unsafe_refusal(tmp_path):
    path = tmp_path / "private"
    assert owner_private_path.create_owner_private_directory(path) == path
    assert owner_private_path.is_owner_private_directory(path)
    owner_private_path.create_owner_private_directory(path)
    if os.name != "nt":
        path.chmod(0o755)
        with pytest.raises(OSError, match="owner_private_directory_unsafe"):
            owner_private_path.create_owner_private_directory(path)
        assert path.stat().st_mode & 0o777 == 0o755


def test_private_write_does_not_create_parents(tmp_path):
    with pytest.raises(OSError):
        owner_private_path.write_owner_private(tmp_path / "missing" / "secret", b"no")
    assert not (tmp_path / "missing").exists()
