"""Carry the Cursor model across the events that can and cannot afford work.

Cursor names the model a terminal-agent session is running on exactly one
event, ``afterAgentThought``, and that event fires inside the token stream —
once per chunk, with the stream held open across the hook. Measured on
cursor-agent 2026.07.23 over six runs each: no hook 6/6 clean, a 0.04s
``echo`` hook 4/4, a 0.25s ``sleep`` hook carrying no Yoke code 2/6. Starting
our Python CLI costs ~0.23s before any of our code runs, so that event cannot
afford to do the work — the agent dies with "RetriableError: WritableIterable
is closed".

Every other Cursor event fires between operations rather than during
generation and already runs the full hook command safely, but none of them
knows the model: they all report the literal ``"default"``.

So the streaming event does the one thing it can afford — append its payload
to a spool file, in shell, with no interpreter — and the next ordinary hook
picks it up and ships the model the normal way. A session that never fires
another hook simply keeps the model it already had, which is the behavior
before any of this existed.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from yoke_cli.config import machine_config


SPOOL_DIR_NAME = "cursor-model-spool"

# Entries are consumed within seconds by the next hook. Anything older than
# this belongs to a run whose session never fired one, and is dropped rather
# than applied to a session that has long since moved on.
_STALE_AGE_S = 3600


def spool_dir() -> Path:
    return machine_config.yoke_home() / SPOOL_DIR_NAME


def capture_command() -> str:
    """The shell the streaming event runs — no interpreter, no Yoke code.

    Resolves the machine home the same way :func:`machine_config.yoke_home`
    does. That rule is expressed twice, in shell and in Python, because the
    whole point is that this side cannot start Python to ask; the directory
    name itself stays single-sourced above.

    Writes one file per fire, named for the shell's own pid, so concurrent
    fires cannot interleave inside a single file. The trailing ``echo {}``
    is Cursor's required reply — an empty stdout drops the model stream.
    """
    home = f'"${{{machine_config.HOME_ENV}:-$HOME/.yoke}}"'
    return (
        f"D={home}/{SPOOL_DIR_NAME}; "
        'mkdir -p "$D"; cat > "$D/$$.json"; echo {}'
    )


def _entry_model(payload: dict) -> str:
    for key in ("model_id", "model"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def drain_model(session_id: str) -> Optional[str]:
    """Return the model this session's spooled payloads name, if any.

    Consumes what it reads: a spooled payload is a one-shot hand-off, and
    leaving it behind would re-ship the same model on every later hook.
    Entries belonging to other sessions are left for their own hook to
    claim. Never raises — a hook must not fail on a bookkeeping file.
    """
    if not session_id:
        return None
    try:
        entries = sorted(spool_dir().iterdir())
    except OSError:
        return None

    model = ""
    for entry in entries:
        try:
            if entry.stat().st_mtime < _stale_before():
                entry.unlink(missing_ok=True)
                continue
            payload = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("session_id") != session_id:
            continue
        model = _entry_model(payload) or model
        try:
            entry.unlink(missing_ok=True)
        except OSError:
            continue
    return model or None


def _stale_before() -> float:
    return time.time() - _STALE_AGE_S


def clear_for_tests(session_id: str = "") -> None:
    """Drop spooled entries. Test helper; no production caller."""
    try:
        for entry in spool_dir().iterdir():
            if session_id and session_id not in entry.read_text(encoding="utf-8"):
                continue
            entry.unlink(missing_ok=True)
    except OSError:
        return


__all__ = [
    "SPOOL_DIR_NAME",
    "capture_command",
    "clear_for_tests",
    "drain_model",
    "spool_dir",
]
