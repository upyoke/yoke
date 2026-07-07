"""Best-effort product-side session anchor writes."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone

from yoke_cli.config import machine_config


def _process_start_time(pid: int) -> str:
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "lstart="],
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def record_session_anchor(session_id: str, *, transcript_path: str = "") -> None:
    """Best-effort product-side session anchor write."""
    if not session_id:
        return
    try:
        pid = os.getppid()
        record = {
            "session_id": session_id,
            "transcript_path": transcript_path or "",
            "anchor_pid": pid,
            "anchor_start_time": _process_start_time(pid),
            "anchor_process_name": "",
            "registered_at": datetime.now(timezone.utc).isoformat(),
        }
        directory = machine_config.yoke_home() / "session-anchors"
        directory.mkdir(parents=True, exist_ok=True)
        final = directory / f"{pid}.json"
        tmp = directory / f".{pid}.json.tmp.{os.getpid()}"
        tmp.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, final)
    except (OSError, ValueError):
        return


__all__ = ["record_session_anchor"]
