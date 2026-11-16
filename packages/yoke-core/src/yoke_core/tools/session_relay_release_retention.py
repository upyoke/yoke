"""Keep rollback packages and packages still held by running processes."""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import re
import sys
from typing import Iterator
from yoke_contracts import platform_file_lock as locks
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.platform_process import process_command_lines
from yoke_contracts.timestamps import parse_instant
from yoke_contracts.relay_release_layout import RELAY_RELEASE_LOCK_NAME, RELAY_RELEASE_USE_LOCK_NAME

from yoke_core.tools.session_relay_release import (
    RELAY_RELEASE_INSTALL_FAILED,
    RELAY_RELEASE_RECEIPT_NAME,
    RelayReleaseError,
    relay_active_release_path,
    relay_release_receipt,
    write_release_json,
)




def prune_relay_releases(state_dir: Path) -> None:
    """Prune under the install lock, after the new pin has verified."""
    releases = (state_dir / "releases").resolve()
    receipt = relay_release_receipt(state_dir)
    current = Path(str(receipt.get("physical_root") or relay_active_release_path(state_dir).resolve(strict=True)))
    if "physical_root" not in receipt:
        receipt["physical_root"] = str(current)
        write_release_json(current / RELAY_RELEASE_RECEIPT_NAME, receipt)
    # Converge receipts written by the installer that shipped before retention.
    # Installation receipts supply the order; unverified directories do not.
    if "previous_release" not in receipt:
        installed = []
        for path in releases.iterdir():
            if path.is_symlink() or not path.is_dir() or path.resolve() == current:
                continue
            try:
                prior = json.loads((path / RELAY_RELEASE_RECEIPT_NAME).read_text(encoding="utf-8"))
            except (FileNotFoundError, ValueError):
                continue
            if isinstance(prior, dict) and prior.get("installed_at"):
                installed.append((str(prior["installed_at"]), str(path.resolve())))
        receipt["previous_release"] = max(installed)[1] if installed else None
        write_release_json(current / RELAY_RELEASE_RECEIPT_NAME, receipt)
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
    try:
        processes = process_command_lines()
        commands = "\n".join(" ".join(process.cmdline) for process in processes)
    except OSError as exc:
        raise RelayReleaseError(
            RELAY_RELEASE_INSTALL_FAILED,
            "relay_release_prune_failed: cannot inspect running processes; "
            "restore access to the OS process snapshot and retry relay install",
        ) from exc
    imported_roots = [Path(value).resolve() for value in sys.path if value]
    launcher_roots = _launcher_release_roots(state_dir, releases, processes)
    for candidate in candidates:
        root = candidate.resolve()
        if root in launcher_roots or re.search(re.escape(str(root)) + r"(?:[/\\\s]|$)", commands) or any(
            value == root or value.is_relative_to(root) for value in imported_roots
        ):
            continue
        # Stable launchers hold a shared file lock for their full lifetime.
        # Taking the pin lock before resolving the active pointer prevents a
        # launcher from selecting a tree while it is being removed.
        with (candidate / RELAY_RELEASE_USE_LOCK_NAME).open(mode="a+b") as handle:
            try:
                locks.acquire_exclusive_nonblocking(handle.fileno())
            except BlockingIOError:
                continue
            # Windows cannot delete an open lock file: close it before
            # deleting the tree.
            # The pin lock prevents a launcher acquiring a new lease here.
            locks.release_exclusive(handle.fileno())
        remove_tree(candidate)


def _launcher_release_roots(state_dir, releases, processes):
    """Protect the release selected by a stable launcher during lock rollout.

    Process start times and installation receipts also protect a launcher
    that predates the file lease. A concurrent pin can only select a newer
    release, whose own shared lease protects it.
    """
    installed = []
    for path in releases.iterdir():
        if not path.is_dir() or path.is_symlink():
            continue
        try:
            receipt = json.loads((path / RELAY_RELEASE_RECEIPT_NAME).read_text(encoding="utf-8"))
            stamp = parse_instant(receipt["installed_at"]).timestamp()
            installed.append((stamp, path.resolve()))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    keep = set()
    prefixes = [str(state_dir / name) for name in ("runtime", "venv")]
    for process in processes:
        if not any(arg.startswith(prefix) for arg in process.cmdline for prefix in prefixes):
            continue
        eligible = [(stamp, path) for stamp, path in installed if stamp <= process.start_time]
        if eligible:
            latest = max(stamp for stamp, _ in eligible)
            keep.update(path for stamp, path in eligible if stamp == latest)
    return keep


@contextmanager
def release_install_lock(state_dir: Path) -> Iterator[None]:
    """Serialize package installs against launchers selecting their release."""
    with (state_dir / RELAY_RELEASE_LOCK_NAME).open(mode="a+b") as handle:
        locks.acquire_exclusive(handle.fileno())
        try:
            yield
        finally:
            locks.release_exclusive(handle.fileno())
