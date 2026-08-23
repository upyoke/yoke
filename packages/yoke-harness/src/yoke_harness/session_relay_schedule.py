"""Process-local locking and disk-backed cadence for launchd relay runs."""

from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import time
from typing import Iterator

from yoke_cli.config.session_relay_instance import (
    PROD_RELAY_STATE_DIR_NAME,
    resolve_relay_instance,
)


RELAY_STATE_DIR_NAME = PROD_RELAY_STATE_DIR_NAME
RELAY_LOCK_FILE_NAME = "serve-once.lock"
RELAY_NEXT_POLL_FILE_NAME = "next-poll-at"


def relay_state_dir() -> Path:
    return resolve_relay_instance().state_dir


def _prepare_state_dir(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass


@contextmanager
def relay_run_lock(
    state_dir: Path | None = None,
) -> Iterator[bool]:
    """Yield whether this fresh process acquired the non-blocking run lock."""
    directory = state_dir or relay_state_dir()
    _prepare_state_dir(directory)
    lock_path = directory / RELAY_LOCK_FILE_NAME
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            pass
        yield acquired
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def poll_is_due(
    state_dir: Path | None = None,
    *,
    now: float | None = None,
) -> bool:
    path = (state_dir or relay_state_dir()) / RELAY_NEXT_POLL_FILE_NAME
    try:
        due_at = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (time.time() if now is None else now) >= due_at


def record_next_poll(
    seconds: int,
    state_dir: Path | None = None,
    *,
    started_at: float,
    now: float | None = None,
) -> None:
    directory = state_dir or relay_state_dir()
    _prepare_state_dir(directory)
    current = time.time() if now is None else now
    due_at = max(current, started_at + max(1, int(seconds)))
    path = directory / RELAY_NEXT_POLL_FILE_NAME
    temporary = path.with_suffix(".tmp")
    temporary.write_text(f"{due_at:.6f}\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


__all__ = [
    "RELAY_LOCK_FILE_NAME",
    "RELAY_NEXT_POLL_FILE_NAME",
    "RELAY_STATE_DIR_NAME",
    "poll_is_due",
    "record_next_poll",
    "relay_run_lock",
    "relay_state_dir",
]
