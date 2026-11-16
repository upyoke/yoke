"""Retain the physical packages of a detached relay worker until it exits."""

from pathlib import Path
from typing import BinaryIO

from yoke_contracts import platform_file_lock as locks
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.relay_release_layout import (
    RELAY_RELEASE_LOCK_NAME, RELAY_RELEASE_USE_LOCK_NAME, RELAY_RELEASE_RECEIPT_NAME,
)


def hold_running_release(module_file: str) -> BinaryIO | None:
    """Lease the release containing this module; source/local installs have none."""
    for root in Path(module_file).resolve().parents:
        if root.parent.name != "releases" or not (root / RELAY_RELEASE_RECEIPT_NAME).is_file():
            continue
        handle = None
        try:
            # Use the same order as selection/pruning: pin, then package lease.
            with (root.parent.parent / RELAY_RELEASE_LOCK_NAME).open(mode="a+b") as pin:
                locks.acquire_shared(pin.fileno())
                try:
                    handle = (root / RELAY_RELEASE_USE_LOCK_NAME).open(mode="a+b")
                    locks.acquire_shared(handle.fileno())
                finally:
                    locks.release_exclusive(pin.fileno())
            return handle
        except OSError as exc:
            if handle is not None:
                handle.close()
            raise SystemExit(
                compose_refusal(
                    f"relay_worker_release_unavailable: {root}: {exc}",
                    recovery="retry the native operation with the current relay release",
                )
            ) from None
    return None
