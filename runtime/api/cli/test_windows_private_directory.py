"""Windows private directories retain a fail-closed DACL boundary."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from yoke_contracts import windows_private_directory


pytestmark = pytest.mark.windows_only(reason='Windows DACL contract')


def test_owner_private_directory_is_accepted(tmp_path: Path) -> None:
    private = tmp_path / "private"
    windows_private_directory.create_private_directory(private)

    assert windows_private_directory.is_private_directory(private) is True


def test_inherited_directory_is_refused(tmp_path: Path) -> None:
    inherited = tmp_path / "inherited"
    inherited.mkdir()

    assert windows_private_directory.is_private_directory(inherited) is False


def test_protect_existing_directory_and_its_new_children(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    existing.mkdir()
    assert not windows_private_directory.is_private_directory(existing)

    windows_private_directory.make_private_directory(existing)

    assert windows_private_directory.is_private_directory(existing)
    child = existing / "secret"
    child.write_bytes(b"private")
    assert windows_private_directory.is_private_file(child)


@pytest.fixture
def inherited_parent(tmp_path: Path) -> Path:
    profile = tmp_path / "profile"
    profile.mkdir()
    windows_private_directory.make_private_directory(profile)
    parent = profile / "exports"
    parent.mkdir()
    assert not windows_private_directory.is_private_directory(parent)
    return parent


def test_file_inherits_only_from_unwritable_parent(inherited_parent: Path) -> None:
    archive = inherited_parent / "universe.tar"
    archive.write_bytes(b"archive")
    assert windows_private_directory.is_private_file(archive)


@pytest.mark.parametrize(
    ("target", "grant"),
    [("file", "*S-1-1-0:(R)"), ("parent", "*S-1-5-32-545:(W)")],
)
def test_inherited_file_rejects_untrusted_access(
    inherited_parent: Path, target: str, grant: str,
) -> None:
    archive = inherited_parent / "universe.tar"
    archive.write_bytes(b"archive")
    subprocess.run(
        ["icacls", str(archive if target == "file" else inherited_parent), "/grant", grant],
        check=True,
    )
    assert not windows_private_directory.is_private_file(archive)
