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
    container_session_id_from_evidence,
    prune_stale_conversation_sessions,
    record_conversation_session as _record_conversation_session,
)
from yoke_harness.hooks.identity_runtime import is_cursor


def _map_dir():
    return machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME


def record_conversation_session(conversation_id: str, session_id: str) -> None:
    """Record that ``conversation_id`` belongs to ``session_id``."""
    _record_conversation_session(conversation_id, session_id, _map_dir())


def record_from_hook_payload(payload: dict, executor: str) -> None:
    """Persist a hook event's conversation -> container session pairing.

    Only the client hook process can: it alone sees this machine's
    transcript env and machine home, and is the side a later Cursor shell
    reads from — the payload adapter shaping these same fields runs
    wherever the chain is evaluated, which over https is the server.

    A Cursor shell carries only its own ``CURSOR_CONVERSATION_ID``, which
    for a dispatched subagent names no registered session, so without this
    every identity-requiring command run there fails. Recorded only
    against evidence naming the container: a wrong pairing is worse than a
    missing one. Never raises — a hook must not fail on bookkeeping.
    """
    if not is_cursor(executor):
        return
    try:
        conversation_id = payload.get("session_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            return
        container = container_session_id_from_evidence(payload)
        if container:
            record_conversation_session(conversation_id, container)
    except Exception:  # noqa: BLE001 — bookkeeping must not break a hook
        return


def prune_stale_conversation_map() -> None:
    """Best-effort cleanup for the recorded pairings at session start."""
    try:
        prune_stale_conversation_sessions(_map_dir())
    except Exception:  # noqa: BLE001 — maintenance must not break a hook
        return


__all__ = [
    "prune_stale_conversation_map",
    "record_conversation_session",
    "record_from_hook_payload",
]
