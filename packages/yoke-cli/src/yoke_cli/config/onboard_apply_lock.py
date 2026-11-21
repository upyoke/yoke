"""Mutual exclusion for setup Apply and the relay's CLI release follow."""

from __future__ import annotations

from yoke_contracts import platform_file_lock
from yoke_contracts.platform_process import pid_alive

from yoke_contracts.machine_config.directories import create_private_directory

import json
import os
from contextlib import contextmanager
from yoke_contracts.timestamps import iso8601_now
from pathlib import Path
from typing import Iterator

from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_checklist

LOCK_NAME = "active-run.lock"


class OnboardApplyBusy(onboard_apply_report.OnboardApplyReportError):
    """Another process holds the setup Apply lock."""


@contextmanager
def acquire(run_id: str = "") -> Iterator[None]:
    path = lock_path()
    create_private_directory(path.parent)
    # Serialize stale-marker cleanup and replacement across new callers. The
    # PID marker still protects setup processes already running across upgrades.
    guard = os.open(path.with_suffix(".guard"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            platform_file_lock.acquire_exclusive_nonblocking(guard)
        except BlockingIOError as exc:
            raise _busy(_holder(path)) from exc
        _remove_stale(path)
        os.close(_open_lock(path, run_id))
    finally:
        os.close(guard)
    try:
        yield
    finally:
        _release(path)


def lock_path() -> Path:
    return (
        onboard_checklist.runs_dir() / onboard_apply_report.REPORTS_DIR_NAME / LOCK_NAME
    )


def _open_lock(path: Path, run_id: str) -> int:
    payload = {
        "pid": os.getpid(),
        "run_id": str(run_id or ""),
        "created_at": iso8601_now(),
    }
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise _busy(_holder(path)) from exc
    os.write(fd, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
    return fd


def _busy(holder: int | None) -> OnboardApplyBusy:
    detail = f" (pid {holder})" if holder else ""
    return OnboardApplyBusy(
        f"another onboarding apply is already running or the relay is "
        f"applying a CLI release{detail}; try again later"
    )


def _remove_stale(path: Path) -> None:
    holder = _holder(path)
    if holder is None or _pid_alive(holder):
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _holder(path: Path) -> int | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        return int(payload.get("pid")) if isinstance(payload, dict) else None
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    return pid_alive(pid)


def _release(path: Path) -> None:
    if _holder(path) != os.getpid():
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


__all__ = ["LOCK_NAME", "acquire", "lock_path"]
