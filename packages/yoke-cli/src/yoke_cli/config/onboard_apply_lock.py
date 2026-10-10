"""Active-run lock for ``yoke setup`` apply."""

from __future__ import annotations

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


@contextmanager
def acquire(run_id: str = "") -> Iterator[None]:
    path = lock_path()
    create_private_directory(path.parent)
    _remove_stale(path)
    fd = _open_lock(path, run_id)
    try:
        os.close(fd)
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
        holder = _holder(path)
        detail = f" by pid {holder}" if holder else ""
        raise onboard_apply_report.OnboardApplyReportError(
            f"another onboarding apply is already running{detail}; try again later"
        ) from exc
    os.write(fd, (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
    return fd


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
        return int(payload.get("pid"))
    except (TypeError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _release(path: Path) -> None:
    if _holder(path) != os.getpid():
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return


__all__ = ["LOCK_NAME", "acquire", "lock_path"]
