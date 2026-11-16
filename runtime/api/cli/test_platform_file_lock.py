"""Platform file locks retain acquisition, contention, and release semantics."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from yoke_contracts import platform_file_lock


def _open_lock(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)


def test_exclusive_lock_contends_then_releases(tmp_path: Path) -> None:
    path = tmp_path / "state.lock"
    holder = _open_lock(path)
    contender = _open_lock(path)
    try:
        platform_file_lock.acquire_exclusive_nonblocking(holder)
        with pytest.raises(BlockingIOError):
            platform_file_lock.acquire_exclusive_nonblocking(contender)

        platform_file_lock.release_exclusive(holder)
        platform_file_lock.acquire_exclusive_nonblocking(contender)
        platform_file_lock.release_exclusive(contender)
    finally:
        os.close(contender)
        os.close(holder)


def test_platform_lock_module_exports_only_portable_operations() -> None:
    assert platform_file_lock.__all__ == [
        "acquire_exclusive",
        "acquire_exclusive_nonblocking",
        "release_exclusive",
        "acquire_shared",
        "acquire_shared_nonblocking",
        "release_shared",
    ]


def test_shared_readers_exclude_writer(tmp_path):
    descriptors = [_open_lock(tmp_path / "shared.lock") for _ in range(3)]
    first, second, writer = descriptors
    try:
        platform_file_lock.acquire_shared_nonblocking(first)
        platform_file_lock.acquire_shared_nonblocking(second)
        with pytest.raises(BlockingIOError):
            platform_file_lock.acquire_exclusive_nonblocking(writer)
        platform_file_lock.release_shared(first)
        with pytest.raises(BlockingIOError):
            platform_file_lock.acquire_exclusive_nonblocking(writer)
        platform_file_lock.release_shared(second)
        platform_file_lock.acquire_exclusive_nonblocking(writer)
        with pytest.raises(BlockingIOError):
            platform_file_lock.acquire_shared_nonblocking(first)
        platform_file_lock.release_exclusive(writer)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
