"""Filesystem advisory lock — canonical Python owner.

Single source of truth for Yoke's directory-based advisory locking.
``rebuild_board`` and ``write_to_main`` re-export from here.

Locking strategy: directory-based mkdir locks (atomic on all POSIX platforms).
A stale lock — one whose mtime is older than ``lock_stale_seconds`` — is
removed before the retry loop and again after exhausting retries.

Configuration (read from ``~/.yoke/config.json`` via ``runtime_settings``):
  - ``lock_retries``       (default 50)
  - ``lock_sleep_ms``      (default 100)
  - ``lock_stale_seconds`` (default 60)

CLI usage::

    python3 -m yoke_core.domain.lock_helper acquire <lockdir> [--config <path>]
    python3 -m yoke_core.domain.lock_helper release <lockdir>
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from yoke_core.domain import runtime_settings
from yoke_core.domain import machine_config


DEFAULT_RETRIES = 50
DEFAULT_SLEEP_MS = 100
DEFAULT_STALE_SECONDS = 60


def _read_lock_settings(config_path: Path) -> tuple[int, float, int]:
    """Return ``(retries, sleep_seconds, stale_seconds)`` for the config."""
    retries = runtime_settings.get_int(
        "lock_retries", DEFAULT_RETRIES, config_path=config_path,
    )
    sleep_ms = runtime_settings.get_int(
        "lock_sleep_ms", DEFAULT_SLEEP_MS, config_path=config_path,
    )
    stale_seconds = runtime_settings.get_int(
        "lock_stale_seconds", DEFAULT_STALE_SECONDS, config_path=config_path,
    )
    return retries, sleep_ms / 1000.0, stale_seconds


def _lock_mtime(path: Path) -> int:
    """Return the integer mtime of ``path``.  ``0`` means the stat failed
    (the lock may have disappeared between check and stat — caller should
    treat this as "not stale" and retry mkdir).
    """
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return 0


def acquire_lock(lock_dir: Path, config_path: Path) -> bool:
    """Acquire an advisory lock by creating ``lock_dir`` via ``mkdir``.

    Retries up to ``lock_retries`` times with ``lock_sleep_ms`` delay between
    attempts.  Breaks stale locks older than ``lock_stale_seconds``.  Returns
    ``True`` on success and ``False`` if the lock cannot be acquired after
    all retries (matching the shell ``acquire_lock`` semantics, which exits
    non-zero on failure).
    """
    retries, sleep_seconds, stale_seconds = _read_lock_settings(config_path)

    def clear_if_stale() -> None:
        if not lock_dir.is_dir():
            return
        mtime = _lock_mtime(lock_dir)
        if mtime <= 0:
            return
        age = int(time.time()) - mtime
        if age > stale_seconds:
            print(
                f"Warning: Removing stale lock (age: {age}s): {lock_dir}",
                file=sys.stderr,
            )
            shutil.rmtree(lock_dir, ignore_errors=True)

    clear_if_stale()
    attempts = 0
    while True:
        try:
            # parents=True so a first-ever rebuild in a repo whose board
            # directory (e.g. .yoke/) does not exist yet creates the ancestor
            # path instead of raising FileNotFoundError; the lock dir itself
            # still raises FileExistsError when held, preserving retry/stale logic.
            lock_dir.mkdir(parents=True)
            return True
        except FileExistsError:
            attempts += 1
            if attempts > retries:
                clear_if_stale()
                if not lock_dir.exists():
                    attempts = 0
                    continue
                return False
            time.sleep(sleep_seconds)


def release_lock(lock_dir: Path) -> None:
    """Release an advisory lock by removing ``lock_dir``.  Failure is
    silently ignored — matching the shell ``release_lock`` semantics, which
    always returns success."""
    try:
        lock_dir.rmdir()
    except OSError:
        shutil.rmtree(lock_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_config_path(lock_dir: Path) -> Path:
    """Best-effort config resolution for CLI callers.

    Priority:
      1. Explicit ``YOKE_MACHINE_CONFIG_FILE``
      2. Default ``~/.yoke/config.json``
    """
    return machine_config.config_path()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lock_helper",
        description="Filesystem advisory lock (acquire/release).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_acq = sub.add_parser("acquire", help="Acquire an advisory lock")
    p_acq.add_argument("lockdir", help="Directory path to create as the lock")
    p_acq.add_argument(
        "--config",
        dest="config",
        default=None,
        help="Path to yoke config (default: auto-resolved)",
    )

    p_rel = sub.add_parser("release", help="Release an advisory lock")
    p_rel.add_argument("lockdir", help="Directory path of the lock to remove")

    args = parser.parse_args(argv)
    lock_dir = Path(args.lockdir)

    if args.cmd == "acquire":
        config_path = Path(args.config) if args.config else _default_config_path(lock_dir)
        if acquire_lock(lock_dir, config_path):
            return 0
        retries, _, _ = _read_lock_settings(config_path)
        print(
            f"Error: Could not acquire lock after {retries} retries: {lock_dir}",
            file=sys.stderr,
        )
        return 1

    if args.cmd == "release":
        release_lock(lock_dir)
        return 0

    parser.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
