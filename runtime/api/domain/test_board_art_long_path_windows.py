"""The board-art loader reads its packaged columns past the Windows MAX_PATH boundary."""
from __future__ import annotations

import os
import zipfile

import pytest

from yoke_contracts.platform_fs import extended_length_path
from yoke_contracts.project_contract.board_art import _data as art_data

_RESOURCE = "mixed_emoji_columns.txt"


def _packaged_resource_bytes() -> bytes:
    resource = art_data._resource_files("yoke_contracts.project_contract.board_art.data").joinpath(_RESOURCE)
    return resource.read_bytes()


def _long_paths_policy() -> str:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
            return str(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except FileNotFoundError:
        return "absent"


@pytest.mark.windows
@pytest.mark.windows_only(reason="MAX_PATH and extended-length paths are native Windows filesystem behavior")
def test_loader_reads_the_packaged_columns_beyond_max_path(tmp_path, monkeypatch, request):
    data = tmp_path
    while len(str(data / _RESOURCE)) <= 300:
        data = data / ("release-generation-" + "x" * 40)
    os.makedirs(extended_length_path(data))
    resource = data / _RESOURCE
    with open(extended_length_path(resource), "wb") as handle:
        handle.write(_packaged_resource_bytes())
    monkeypatch.setattr(art_data, "_resource_files", lambda package: data)

    assert len(str(resource)) > 260
    assert os.path.isfile(extended_length_path(resource))
    try:
        ordinary = resource.read_text(encoding="utf-8")
    except FileNotFoundError:
        ordinary = None
    # The JUnit report carries the native boundary outcome as evidence.
    request.node.user_properties += [
        ("path_length", len(str(resource))),
        ("ordinary_read", "failed" if ordinary is None else "succeeded"),
        ("long_paths_enabled", _long_paths_policy()),
    ]
    if ordinary is not None:
        assert art_data._parse_mixed_emoji_columns(ordinary) == art_data.MIXED_EMOJI_COLUMNS
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
