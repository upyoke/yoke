"""Crash recovery and serialization tests for self-host atomic files."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
import threading
import time

import pytest

from yoke_cli.self_host import atomic_file


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_next_write_cleans_owned_orphan_without_following_symlink(tmp_path):
    target = tmp_path / "github-app-private-key.pem"
    orphan = tmp_path / ".github-app-private-key.pem.crashed.tmp"
    orphan.write_bytes(b"stranded-key\n")
    orphan.chmod(0o600)
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"keep\n")
    symlink = tmp_path / ".github-app-private-key.pem.link.tmp"
    symlink.symlink_to(sentinel)
    unrelated = tmp_path / ".another-key.crashed.tmp"
    unrelated.write_bytes(b"unrelated\n")
    near_match = tmp_path / ".github-app-private-key.pem.crashed.tmp.keep"
    near_match.write_bytes(b"near-match\n")

    atomic_file.atomic_replace_bytes(target, b"current-key\n", mode=0o600)

    assert target.read_bytes() == b"current-key\n"
    assert not orphan.exists()
    assert symlink.is_symlink()
    assert sentinel.read_bytes() == b"keep\n"
    assert unrelated.read_bytes() == b"unrelated\n"
    assert near_match.read_bytes() == b"near-match\n"
    lock_path = atomic_file.target_lock_path(target)
    assert lock_path.is_file()
    assert _mode(lock_path) == 0o600


def test_persistent_lock_serializes_concurrent_writers(tmp_path, monkeypatch):
    target = tmp_path / "db-password"
    payloads = tuple(f"password-{index}\n".encode() for index in range(6))
    counter_lock = threading.Lock()
    active_replacements = 0
    maximum_active = 0
    real_replace = atomic_file.os.replace

    def _slow_replace(source, destination):
        nonlocal active_replacements, maximum_active
        with counter_lock:
            active_replacements += 1
            maximum_active = max(maximum_active, active_replacements)
        try:
            time.sleep(0.03)
            real_replace(source, destination)
        finally:
            with counter_lock:
                active_replacements -= 1

    monkeypatch.setattr(atomic_file.os, "replace", _slow_replace)
    with ThreadPoolExecutor(max_workers=len(payloads)) as executor:
        results = list(
            executor.map(
                lambda payload: atomic_file.atomic_replace_bytes(
                    target,
                    payload,
                    mode=0o600,
                ),
                payloads,
            )
        )

    assert results == [target] * len(payloads)
    assert maximum_active == 1
    assert target.read_bytes() in payloads
    assert _mode(target) == 0o600
    assert _mode(atomic_file.target_lock_path(target)) == 0o600
    assert not list(tmp_path.glob(f".{target.name}.*.tmp"))


def test_persistent_lock_refuses_symlink_without_following_it(tmp_path):
    target = tmp_path / "dsn"
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"keep\n")
    lock_path = atomic_file.target_lock_path(target)
    lock_path.symlink_to(sentinel)

    with pytest.raises(atomic_file.AtomicFileError):
        atomic_file.atomic_replace_bytes(target, b"secret\n", mode=0o600)

    assert lock_path.is_symlink()
    assert sentinel.read_bytes() == b"keep\n"
    assert not target.exists()
