"""Best-effort Cursor conversation-to-session recording from hook processes.

Binds the shared body in :mod:`yoke_contracts.cursor_session_map` to the
product CLI's machine home, the same split (and for the same reason) as
:mod:`yoke_harness.hooks.identity_anchor`. Hook processes are the only
place both ids are visible at once, so they are the only place the pairing
can be written; every later shell is a reader.
"""

from __future__ import annotations

from yoke_cli.config import machine_config
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    prune_stale_conversation_sessions,
    record_conversation_session as _record_conversation_session,
)


def _map_dir():
    return machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME


def record_conversation_session(conversation_id: str, session_id: str) -> None:
    """Record that ``conversation_id`` belongs to ``session_id``."""
    _record_conversation_session(conversation_id, session_id, _map_dir())


def prune_stale_conversation_map() -> None:
    """Best-effort cleanup for the recorded pairings at session start."""
    try:
        prune_stale_conversation_sessions(_map_dir())
    except Exception:  # noqa: BLE001 — maintenance must not break a hook
        return


__all__ = ["prune_stale_conversation_map", "record_conversation_session"]
