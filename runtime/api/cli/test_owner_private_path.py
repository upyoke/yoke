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
    assert owner_private_path.__all__ == ["is_owner_private_file"]
