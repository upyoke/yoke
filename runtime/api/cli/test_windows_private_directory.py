"""Windows private directories retain a fail-closed DACL boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_contracts import windows_private_directory


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows DACL contract")


def test_owner_private_directory_is_accepted(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    assert windows_private_directory.is_private_directory(private) is True


def test_inherited_directory_is_refused(tmp_path: Path) -> None:
    inherited = tmp_path / "inherited"
    inherited.mkdir()

    assert windows_private_directory.is_private_directory(inherited) is False


def test_file_inherits_only_from_private_parent(tmp_path: Path) -> None:
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    protected_file = private / "config.json.lock"
    protected_file.touch(mode=0o600)

    assert windows_private_directory.is_private_file(protected_file) is True
