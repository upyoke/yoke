"""Read a completed Codex command's native duration on the harness machine."""

from __future__ import annotations

import json
from typing import Any, Mapping

from yoke_contracts.cursor_shell_timing import native_duration_ms
from yoke_contracts.turn_end_evidence import read_transcript_tail


def command_duration_ms(payload: Mapping[str, Any]) -> int | None:
    """Match the hook's exact call identity; never time the model's check-backs.

    Codex CommandExecution items expose Rust Duration as seconds/nanoseconds.
    Missing, unreadable or incomplete rollout evidence leaves the existing
    captured-hook measurement available, rather than inventing command time.
    """
    supplied = native_duration_ms(payload)
    if supplied is not None:
        return supplied
    call_id = payload.get("tool_use_id")
    path = payload.get("transcript_path")
    if not isinstance(call_id, str) or not call_id:
        return None
    if not isinstance(path, str) or not path:
        return None
    text = read_transcript_tail(path)
    for raw in reversed((text or "").splitlines()):
        try:
            record = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(record, dict) or record.get("type") != "event_msg":
            continue
        event = record.get("payload")
        if not isinstance(event, dict) or event.get("type") != "item_completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "CommandExecution":
            continue
        if item.get("id") != call_id:
            continue
        duration = item.get("duration")
        if not isinstance(duration, dict):
            return None
        secs, nanos = duration.get("secs"), duration.get("nanos")
        if any(type(value) is not int for value in (secs, nanos)):
            return None
        if secs < 0 or not 0 <= nanos < 1_000_000_000:
            return None
        return secs * 1000 + (nanos + 500_000) // 1_000_000
    return None
