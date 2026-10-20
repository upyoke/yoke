"""Keep rollback packages and packages still held by running processes."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Iterator

from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_INSTALL_FAILED,
    RelayReleaseError,
    relay_active_release_path,
    relay_release_receipt,
)


RELAY_RELEASE_LOCK_NAME = "release-pin.lock"


def prune_relay_releases(state_dir: Path) -> None:
    """Prune under the install lock, after the new pin has verified."""
    releases = (state_dir / "releases").resolve()
    current = relay_active_release_path(state_dir).resolve(strict=True)
    receipt = relay_release_receipt(state_dir)
    previous = receipt.get("previous_release")
    keep = {current}
    if previous:
        keep.add(Path(previous).resolve())
    candidates = [
        path
        for path in releases.iterdir()
        if path.is_dir() and not path.is_symlink() and path.resolve() not in keep
    ]
    if not candidates:
        return
    # Direct release interpreters and children can predate the stable launcher.
    # Never emit the process table: command lines may contain credentials.
    result = subprocess.run(
        ["ps", "axeww", "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode:
        raise RelayReleaseError(
            RELAY_RELEASE_INSTALL_FAILED,
            "relay_release_prune_failed: cannot inspect running processes; "
            "restore access to ps and retry relay install",
        )
    imported_roots = [Path(value).resolve() for value in sys.path if value]
    for candidate in candidates:
        root = candidate.resolve()
        if re.search(re.escape(str(root)) + r"(?:[/\s]|$)", result.stdout) or any(
            value == root or value.is_relative_to(root) for value in imported_roots
        ):
            continue
        # Stable launchers hold a shared directory lock for their full lifetime.
        # Taking the pin lock before resolving the active pointer prevents a
        # launcher from selecting a tree while it is being removed.
        descriptor = os.open(candidate, os.O_RDONLY)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                continue
            shutil.rmtree(candidate)
        finally:
            os.close(descriptor)


@contextmanager
def release_install_lock(state_dir: Path) -> Iterator[None]:
    """Serialize package installs against launchers selecting their release."""
    with (state_dir / RELAY_RELEASE_LOCK_NAME).open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
