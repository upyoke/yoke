"""Durable process-group custody for the machine-local browser daemon."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_contracts import platform_process

PROCESS_RECORD_NAME = ".daemon-process.json"


def record_group(directory: Path, group) -> None:
    """Publish the exact OS identities before waiting for daemon readiness."""
    path = directory / PROCESS_RECORD_NAME
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(group.to_record()), encoding="utf-8")
    temporary.replace(path)


def stop_recorded_group(directory: Path, pid: int, *, timeout: float = 5) -> None:
    """Stop only the persisted group, refusing an absent or mismatched identity."""
    path = directory / PROCESS_RECORD_NAME
    try:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if not platform_process.pid_alive(pid):
                return
            raise
        group = platform_process.GroupHandle.from_record(record)
        if group.pid != pid:
            raise ValueError("daemon pid does not match its process record")
        platform_process.stop_group(group, timeout)
    except (OSError, ValueError, KeyError, TypeError, TimeoutError) as exc:
        raise RuntimeError(
            f"browser_daemon_stop_failed: {exc}; inspect the daemon's process "
            "record and local process access, or wait for its idle exit, then "
            "rerun `yoke qa browser setup`."
        ) from None
    path.unlink(missing_ok=True)
