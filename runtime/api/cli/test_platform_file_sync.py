"""Directory durability follows each platform's supported contract."""

from __future__ import annotations

import os
from pathlib import Path

from yoke_contracts import platform_file_sync


def test_sync_directory_uses_directory_fsync_on_posix(
    monkeypatch,
    tmp_path: Path,
) -> None:
    opened: list[tuple[object, int]] = []
    synced: list[int] = []
    closed: list[int] = []
    monkeypatch.setattr(platform_file_sync.os, "name", "posix")
    monkeypatch.setattr(
        platform_file_sync.os,
        "open",
        lambda path, flags: opened.append((path, flags)) or 41,
    )
    monkeypatch.setattr(
        platform_file_sync.os, "fsync", lambda descriptor: synced.append(descriptor)
    )
    monkeypatch.setattr(
        platform_file_sync.os, "close", lambda descriptor: closed.append(descriptor)
    )

    platform_file_sync.sync_directory(tmp_path)

    assert opened == [(tmp_path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))]
    assert synced == [41]
    assert closed == [41]


def test_sync_directory_is_unavailable_on_windows(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(platform_file_sync.os, "name", "nt")
    monkeypatch.setattr(
        platform_file_sync.os,
        "open",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not open")),
    )

    platform_file_sync.sync_directory(tmp_path)


def test_platform_sync_module_exports_only_portable_operation() -> None:
    assert platform_file_sync.__all__ == ["sync_directory"]
