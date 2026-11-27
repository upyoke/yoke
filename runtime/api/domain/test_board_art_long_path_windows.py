"""The board-art loader reads its packaged columns past the Windows MAX_PATH boundary."""
from __future__ import annotations

import ctypes
import os
import zipfile

import pytest

from yoke_contracts.platform_fs import extended_length_path
from yoke_contracts.project_contract.board_art import _data as art_data

_RESOURCE = "mixed_emoji_columns.txt"


def _packaged_resource_bytes() -> bytes:
    resource = art_data._resource_files("yoke_contracts.project_contract.board_art.data").joinpath(_RESOURCE)
    return resource.read_bytes()


def _long_paths_enabled() -> bool:
    probe = ctypes.WinDLL("ntdll").RtlAreLongPathsEnabled
    probe.restype = ctypes.c_ubyte
    return bool(probe())


@pytest.mark.windows
@pytest.mark.windows_only(reason="MAX_PATH and extended-length paths are native Windows filesystem behavior")
def test_loader_reads_the_packaged_columns_beyond_max_path(tmp_path, monkeypatch):
    data = tmp_path
    while len(str(data / _RESOURCE)) <= 300:
        data = data / ("release-generation-" + "x" * 40)
    os.makedirs(extended_length_path(data))
    resource = data / _RESOURCE
    with open(extended_length_path(resource), "wb") as handle:
        handle.write(_packaged_resource_bytes())
    monkeypatch.setattr(art_data, "_resource_files", lambda package: data)

    long_paths = _long_paths_enabled()
    print(f"path length {len(str(resource))}; process long paths enabled: {long_paths}")
    if long_paths:
        assert resource.read_text(encoding="utf-8")
    else:
        with pytest.raises(FileNotFoundError):
            resource.read_text(encoding="utf-8")
    assert art_data._load_mixed_emoji_columns() == art_data.MIXED_EMOJI_COLUMNS
    assert len(art_data.MIXED_EMOJI_COLUMNS) > 1


def test_loader_reads_the_installed_package_resource():
    assert art_data._load_mixed_emoji_columns() == art_data.MIXED_EMOJI_COLUMNS
    assert len(art_data.MIXED_EMOJI_COLUMNS) > 1


def test_non_filesystem_loader_keeps_its_own_resource_read(tmp_path, monkeypatch):
    archive = tmp_path / "package.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(f"data/{_RESOURCE}", _packaged_resource_bytes())
    monkeypatch.setattr(art_data, "_resource_files", lambda package: zipfile.Path(archive, "data/"))

    assert art_data._load_mixed_emoji_columns() == art_data.MIXED_EMOJI_COLUMNS
