"""Fresh Windows machine locks establish ownership before accepting writes."""

import os
import subprocess

import pytest

from yoke_cli.config import machine_config_file
from yoke_contracts import platform_file_lock, windows_private_directory

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(os.name != "nt", reason="real Windows file security"),
]


def test_fresh_machine_lock_is_private_and_reused(tmp_path):
    config = tmp_path / "private" / "config.json"
    lock = machine_config_file.config_lock_path(config)
    with machine_config_file.exclusive_lock(config):
        assert windows_private_directory.is_private_file(lock)
        identity = lock.stat().st_ino
        with lock.open(mode="r+b") as second:
            with pytest.raises(BlockingIOError):
                platform_file_lock.acquire_exclusive_nonblocking(second.fileno())
    with machine_config_file.exclusive_lock(config):
        assert lock.stat().st_ino == identity
        assert windows_private_directory.is_private_file(lock)


def test_existing_unsafe_lock_is_refused_without_repair(tmp_path):
    home = tmp_path / "private"
    windows_private_directory.create_private_directory(home)
    config = home / "config.json"
    lock = machine_config_file.config_lock_path(config)
    descriptor = windows_private_directory.create_private_file(lock)
    os.close(descriptor)
    lock.write_bytes(b"preserve existing lock")
    subprocess.run(
        ["icacls", str(lock), "/grant", "*S-1-1-0:(R)"],
        check=True, capture_output=True,
    )
    assert not windows_private_directory.is_private_file(lock)
    with pytest.raises(machine_config_file.MachineConfigFileError, match="not owner-only"):
        with machine_config_file.exclusive_lock(config):
            pytest.fail("unsafe existing lock accepted")
    assert lock.read_bytes() == b"preserve existing lock"
    assert not windows_private_directory.is_private_file(lock)


def test_private_creation_never_replaces_existing_file(tmp_path):
    target = tmp_path / "existing"
    target.write_bytes(b"unchanged")
    identity = target.stat().st_ino
    with pytest.raises(FileExistsError):
        windows_private_directory.create_private_file(target)
    assert target.read_bytes() == b"unchanged"
    assert target.stat().st_ino == identity
