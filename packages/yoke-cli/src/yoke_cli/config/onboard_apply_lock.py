"""Active-run lock for ``yoke onboard`` apply."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from yoke_cli.config import onboard_apply_report
from yoke_cli.config import onboard_checklist

LOCK_NAME = "active-run.lock"


@contextmanager
def acquire(run_id: str = "") -> Iterator[None]:
    path = lock_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _remove_stale(path)
    fd = _open_lock(path, run_id)
    try:
        os.close(fd)
        yield
    finally:
        _release(path)


def lock_path() -> Path:
    return onboard_checklist.runs_dir() / onboard_apply_report.REPORTS_DIR_NAME / LOCK_NAME


def _open_lock(path: Path, run_id: str) -> int:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        holder = _holder(path)
        detail = f" by pid {holder}" if holder else ""
        raise onboard_apply_report.OnboardApplyReportError(
            f"another onboarding apply is already running{detail}; try again later"
        ) from exc
    payload = {
        "pid": os.getpid(),
        "run_id": str(run_id or ""),
        "created_at": datetime.now(timezone.utc).replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
    }
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
