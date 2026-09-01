"""Read back the context window Claude Code reports it is serving.

Claude states the served window in exactly one machine-readable place: the
JSON it pipes on stdin to the configured status line command, as
``context_window.context_window_size``. Its hook payloads carry session id,
transcript path, permission mode and effort but never the window; its
transcript rows carry per-message usage but never the window; and the only
window-shaped environment variable it reads, ``CLAUDE_CODE_MAX_CONTEXT_TOKENS``,
is an operator override it consumes rather than a value it reports. So the
status line is the whole channel, which is why Yoke configures one.

The status line runs as its own short-lived process, so what it reads has
to outlive it: it records the window under the session id, and the ordinary
attestation path picks it up from there on the next hook event and relays
it like any other served fact. Machine-local by construction — only a
process on the machine running Claude Code is handed the status line JSON
at all, which is the same reason the Cursor model read lives on this side.

Rendering the line is the other half of the bargain. Claude allows one
status line per session, so taking the slot means Yoke owes the operator a
line worth having; this one answers, from the payload alone and with no
database read on a surface that refreshes per turn, which model is serving,
how wide its window is, and how much of it is gone.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Mapping, Optional


#: Recorded windows live beside the other machine-local relay state.
RECORD_DIR_NAME = "claude-served-context"

#: A recording outlives its session only long enough to be read by the next
#: hook event; a week is generous and keeps the directory from growing
#: without bound on a machine that runs many sessions.
RECORD_PRUNE_AGE_S = 7 * 86400


def record_path(session_id: str) -> Optional[Path]:
    """Return the file recording *session_id*'s window, or ``None``.

    ``None`` for any id that could name a path outside the directory: the
    id arrives from a harness payload, and a recording is written before
    anything has validated it.
    """
    if not _safe_session_id(session_id):
        return None
    from yoke_cli.config import machine_config

    return machine_config.yoke_home() / RECORD_DIR_NAME / session_id


def record_context_window(payload: Mapping[str, Any]) -> Optional[int]:
    """Record the window a status line payload states, and return it.

    ``None`` means the payload stated no usable window — an early refresh,
    a foreign payload, an unwritable home — and records nothing, because a
    session with no recording reads as unattested rather than as 200k.
    """
    window = context_window_of(payload)
    session_id = _text(payload.get("session_id"))
    if window is None:
        return None
    target = record_path(session_id)
    if target is None:
        return window
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{window}\n", encoding="utf-8")
        _prune(target.parent)
    except OSError:
        return window
    return window


def recorded_context_window(session_id: str) -> Optional[int]:
    """Return the window recorded for *session_id*, or ``None``."""
    target = record_path(session_id)
    if target is None:
        return None
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    return _positive_int(raw.strip())


def context_window_of(payload: Mapping[str, Any]) -> Optional[int]:
    """Return the window a status line payload states outright."""
    block = payload.get("context_window")
    if not isinstance(block, Mapping):
        return None
    return _positive_int(block.get("context_window_size"))


def status_line(payload: Mapping[str, Any]) -> str:
    """Render the one line Yoke shows in exchange for the status line slot.

    Every part is dropped rather than guessed when the payload has not
    stated it: usage is null before the first API call of a session and
    again after a compact, and a line that printed ``0%`` there would
    report a fresh context that is not fresh.
    """
    parts = [part for part in (_model_label(payload), _window_label(payload)) if part]
    used = _used_percentage(payload)
    if used is not None:
        parts.append(f"{used}% used")
    return " · ".join(parts)


def main(argv: Optional[list[str]] = None) -> int:
    """Record the served window and print the status line.

    Claude re-runs this on every turn and discards a non-zero exit, so the
    contract is to stay silent and harmless on anything unexpected: an
    unparseable payload prints nothing rather than an error, because the
    status line is a display surface and a traceback in it would be the
    most visible possible way to report the least important failure.
    """
    del argv
    import sys

    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError, OSError):
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        record_context_window(payload)
    except Exception:  # noqa: BLE001 — the display must survive the record
        pass
    line = status_line(payload)
    if line:
        sys.stdout.write(line + "\n")
    return 0


def _model_label(payload: Mapping[str, Any]) -> str:
    model = payload.get("model")
    if not isinstance(model, Mapping):
        return ""
    return _text(model.get("display_name")) or _text(model.get("id"))


def _window_label(payload: Mapping[str, Any]) -> str:
    """Spell the window the way an operator says it: ``1M``, ``200K``."""
    window = context_window_of(payload)
    if window is None:
        return ""
    if window >= 1_000_000 and window % 1_000_000 == 0:
        return f"{window // 1_000_000}M"
    if window >= 1_000 and window % 1_000 == 0:
        return f"{window // 1_000}K"
    return str(window)


def _used_percentage(payload: Mapping[str, Any]) -> Optional[int]:
    block = payload.get("context_window")
    if not isinstance(block, Mapping):
        return None
    value = block.get("used_percentage")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0, min(100, int(value)))


def _positive_int(value: object) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _safe_session_id(value: object) -> bool:
    """Reject anything that could escape the recording directory."""
    text = _text(value)
    if not text or len(text) > 128:
        return False
    if os.sep in text or "/" in text or text in {".", ".."}:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._-]+", text))


def _prune(directory: Path) -> None:
    cutoff = time.time() - RECORD_PRUNE_AGE_S
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "RECORD_DIR_NAME",
    "RECORD_PRUNE_AGE_S",
    "context_window_of",
    "main",
    "record_context_window",
    "record_path",
    "recorded_context_window",
    "status_line",
]
