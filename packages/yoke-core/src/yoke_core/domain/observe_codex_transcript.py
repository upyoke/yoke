"""Codex transcript reconciliation for observe telemetry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

# Cap transcript reads so per-hook reconciliation cost stays bounded.
_TRANSCRIPT_TAIL_BYTES = 2 * 1024 * 1024


def _reconcile_codex_exit_code(
    transcript_path: str, tool_use_id: str
) -> Optional[Tuple[int, str]]:
    """Return ``(exit_code, status)`` for a Codex transcript tool call."""
    if not transcript_path or not tool_use_id:
        return None
    try:
        file_path = Path(transcript_path)
        if not file_path.is_file():
            return None
        size = file_path.stat().st_size
        seek_pos = max(0, size - _TRANSCRIPT_TAIL_BYTES)
        with open(file_path, "rb") as fh:
            if seek_pos:
                fh.seek(seek_pos)
                fh.readline()
            chunk = fh.read()
    except OSError:
        return None

    match: Optional[Tuple[int, str]] = None
    for raw in chunk.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
            continue
        if not isinstance(obj, dict):
            continue
        payload = obj.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") != "exec_command_end":
            continue
        if payload.get("call_id") != tool_use_id:
            continue
        exit_code_raw = payload.get("exit_code")
        status = payload.get("status")
        if not isinstance(exit_code_raw, int):
            continue
        match = (exit_code_raw, str(status) if status is not None else "")
    return match
