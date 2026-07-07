"""Stray yoke.db detection at repo root.

Sibling of ``db_error_hook``. Owns the StrayDbResult dataclass and the
``detect_stray_db`` analyzer that handles zero-byte autoremoval and
non-empty stray flagging for the PostToolUse hook pipeline.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class StrayDbResult:
    """Result of stray DB detection at repo root."""

    detected: bool = False
    status: str = ""  # "zero-byte" or "non-empty"
    path: str = ""
    message: str = ""


def detect_stray_db(
    repo_root: str,
    command: str = "???",
) -> StrayDbResult:
    """Detect and handle stray yoke.db at repo root.

    Zero-byte strays are auto-removed.  Non-empty strays are logged.
    Returns a result with a message to inject into agent context.
    """
    stray_path = os.path.join(repo_root, "yoke.db")
    if not os.path.isfile(stray_path):
        return StrayDbResult()

    log_dir = os.path.join(repo_root, "runtime", "ouroboros")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "stray-db-creation.log")

    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        size = os.path.getsize(stray_path)
    except OSError:
        size = 0

    if size == 0:
        _log_line = f"{ts} STRAY-DB-DETECTED at {stray_path} | command: {command[:500]}"
        _append_log(log_path, _log_line)
        try:
            os.remove(stray_path)
        except OSError:
            pass
        return StrayDbResult(
            detected=True,
            status="zero-byte",
            path=stray_path,
            message=(
                f"HARD STOP: This Bash command created a stray repo-root yoke.db at {stray_path}. "
                "Do NOT trust results from that accidental DB. Use Postgres "
                "authority through `YOKE_PG_DSN` or the Python-owned "
                "`python3 -m yoke_core.cli.db_router`, then re-run."
            ),
        )

    _log_line = (
        f"{ts} STRAY-DB-NONEMPTY at {stray_path} ({size} bytes) "
        f"| command: {command[:500]}"
    )
    _append_log(log_path, _log_line)
    return StrayDbResult(
        detected=True,
        status="non-empty",
        path=stray_path,
        message=(
            f"HARD STOP: This Bash command created a non-empty stray repo-root yoke.db at {stray_path}. "
            "Do NOT continue from that accidental DB without manual cleanup and a corrected "
            "Postgres authority. Use `YOKE_PG_DSN` or "
            "`python3 -m yoke_core.cli.db_router` and re-run."
        ),
    )


def _append_log(path: str, line: str) -> None:
    try:
        with open(path, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass
