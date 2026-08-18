"""Pre-relay identity refusal, replay gating, and client-anchor bookkeeping.

Extracted from the relay module so ``relay.py`` stays at the 350-line cap
while the refusal, conversation-shaped rejection, and replay skips live
in one place.
"""

from __future__ import annotations

import json
import sys
from typing import Any, Mapping, Optional

from yoke_contracts.execution_provenance import (
    collect_execution_provenance,
    format_provenance_line,
)
from yoke_contracts.payload_session_fold import (
    HOOK_REPLAY_ENV,
    is_conversation_shaped_session_id,
    is_hook_replay,
)
from yoke_contracts.cursor_remount_expect import (
    REMOUNT_OBSERVING,
    REMOUNT_REFUSAL_PAYLOAD_FIELD,
)
from yoke_harness.hooks.identity import (
    is_codex,
    resolve_session_id,
)
from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT


RELAY_REFUSAL_UNSTAMPED = (
    "Yoke hook relay refused: payload has no stamped, non-conversation "
    "session id. Repair: record the conversation-to-session map on the "
    "client (first hook or remount), then retry. "
    "yoke ouroboros field-note append --kind failed --evidence "
    "'hook relay refused: unstamped session id'"
)
RELAY_REFUSAL_CONVERSATION = (
    "Yoke hook relay refused: session id is still conversation-shaped. "
    "A conversation id must fold through the cursor-session-map before "
    "relay. Repair: record the pairing, then retry."
)


def _cursor_fold_refusal(payload: Mapping[str, Any]) -> Optional[str]:
    refusal = payload.get(REMOUNT_REFUSAL_PAYLOAD_FIELD)
    if not isinstance(refusal, Mapping):
        return None
    holder = str(refusal.get("holder_session_id") or "unknown")
    lane = str(refusal.get("lane") or "unknown")
    conversation = str(refusal.get("arriving_conversation_id") or "unknown")
    if refusal.get("outcome") == REMOUNT_OBSERVING:
        liveness = "the holder conversation has not yet been observed quiet"
    else:
        liveness = (
            "the holder conversation emitted another hook after the remount "
            "candidate arrived"
        )
    return (
        "Yoke Cursor worktree fold refused: conversation "
        f"{conversation} cannot alias holder session {holder} on lane {lane}; "
        f"{liveness}. Continue in the holding conversation or release "
        "its work claim before using this window."
    )


def parse_hook_payload(stdin_data: str) -> dict:
    try:
        payload = json.loads(stdin_data) if stdin_data else None
    except (json.JSONDecodeError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def record_client_anchor(payload: dict, *, session_start: bool = False) -> None:
    if is_hook_replay():
        return
    try:
        from yoke_harness.hooks import relay as relay_mod

        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id or session_id == "unknown":
            return
        tp = payload.get("transcript_path")
        if session_start:
            relay_mod.prune_stale_session_anchors()
        relay_mod.record_session_anchor(
            session_id,
            transcript_path=tp if isinstance(tp, str) else "",
        )
    except Exception:
        return


def capture_codex_session(event_name: str, stdin_data: str, executor: str) -> None:
    if is_hook_replay():
        return
    if event_name != SESSION_START_EVENT or not is_codex(executor):
        return
    try:
        from yoke_harness.hooks import relay as relay_mod

        sid = resolve_session_id(stdin_data)
        if sid:
            relay_mod.write_runtime_cache(sid, stdin_data)
    except Exception:
        return



def print_execution_provenance(
    server: Optional[Mapping[str, Any]] = None,
    *,
    fallback_local: bool = False,
) -> None:
    sys.stderr.write(
        format_provenance_line(
            collect_execution_provenance(), server, fallback_local=fallback_local,
        )
        + chr(10)
    )


def deny_unstamped_relay(payload: Mapping[str, Any]) -> Optional[int]:
    """Print refusal + provenance and return exit 2, or None if ok."""
    message = refuse_unstamped_relay(payload)
    if message is None:
        return None
    sys.stderr.write(message + chr(10))
    print_execution_provenance()
    sys.stdout.write(message + chr(10))
    return 2


def refuse_unstamped_relay(payload: Mapping[str, Any]) -> Optional[str]:
    """Return a deny message when the payload is not safe to relay."""
    fold_refusal = _cursor_fold_refusal(payload)
    if fold_refusal is not None:
        return fold_refusal
    if payload.get("identity_stamped") is True:
        sid = payload.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return None
    sid = payload.get("session_id")
    if not isinstance(sid, str) or not sid.strip():
        return RELAY_REFUSAL_UNSTAMPED
    if is_conversation_shaped_session_id(payload, session_id=sid):
        return RELAY_REFUSAL_CONVERSATION
    return None


__all__ = [
    "HOOK_REPLAY_ENV",
    "RELAY_REFUSAL_CONVERSATION",
    "RELAY_REFUSAL_UNSTAMPED",
    "capture_codex_session",
    "deny_unstamped_relay",
    "is_hook_replay",
    "parse_hook_payload",
    "print_execution_provenance",
    "record_client_anchor",
    "refuse_unstamped_relay",
]
