"""The shared Windows-drive checkout predicate and warning used by doctor and setup."""

from __future__ import annotations

import types

import pytest

from yoke_contracts import windows_drive_checkout as drive


@pytest.mark.parametrize("path", ["/mnt/c/x", "/mnt/d", "/mnt/D/app"])
def test_windows_drive_mounts_match(path: str) -> None:
    assert drive.is_windows_drive_path(path)


@pytest.mark.parametrize("path", ["/home/u/x", "/mnt/data/x", "/mnt", "mnt/c/x"])
def test_linux_paths_do_not_match(path: str) -> None:
    assert not drive.is_windows_drive_path(path)


def test_warning_names_the_path_on_linux(monkeypatch) -> None:
    monkeypatch.setattr(drive, "sys", types.SimpleNamespace(platform="linux"))
    warning = drive.windows_drive_checkout_warning("/mnt/c/x")
    assert warning is not None
    assert warning.startswith("/mnt/c/x is on a Windows drive.")
    assert drive.windows_drive_checkout_warning("/home/u/x") is None


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_no_warning_off_linux(monkeypatch, platform: str) -> None:
    monkeypatch.setattr(drive, "sys", types.SimpleNamespace(platform=platform))
    assert drive.windows_drive_checkout_warning("/mnt/c/x") is None
