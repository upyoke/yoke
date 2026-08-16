"""Fold a hook payload session id through the Cursor conversation map.

``payload.session_id`` is not always a Yoke session. Cursor puts the
conversation id there; trusting it raw compares a conversation to a
claim holder and denies the real occupant as foreign. This helper is
the single fold both the client stamp and the lint-side resolver use.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Union

from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    recorded_session_id_for_conversation,
)

_MapDir = Union[str, "os.PathLike[str]"]


def fold_payload_session_id(
    payload: Mapping[str, Any],
    map_dir: _MapDir,
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Fold ``payload.session_id`` through the conversation map.

    Returns ``None`` when the payload carries no session id — the caller
    uses the ambient chain. Returns ``""`` when the id is a conversation
    that cannot be mapped: empty beats wrong, and a conversation id must
    never pass as a session id. Otherwise returns the mapped session, or
    the raw id when it is not a conversation id.
    """
    raw = payload.get("session_id")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip()
    mapped = recorded_session_id_for_conversation(map_dir, raw)
    if mapped:
        return mapped
    source = os.environ if env is None else env
    aliases = (
        payload.get("conversation_id"),
        payload.get("remapped_conversation_id"),
        source.get(CURSOR_CONVERSATION_ENV_VAR),
    )
    if any(isinstance(alias, str) and alias.strip() == raw for alias in aliases):
        return ""
    return raw


__all__ = ["fold_payload_session_id"]
