"""Stamp hook payloads with canonical ambient session identity.

The client hook process is the only side that can see this machine's
env chain, process-anchor registry, and cursor-session-map. Recording
the Cursor conversation pairing must happen on the original payload
(the conversation id still lives on ``session_id``); stamping the
resolved Yoke session onto ``payload.session_id`` and the folded Cursor
container onto ``payload.container_session_id`` happens after that so
the lint chain never re-resolves either conversation-shaped channel.
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from yoke_cli.config import machine_config
from yoke_contracts.cursor_session_map import container_session_id_from_evidence
from yoke_contracts.payload_session_fold import (
    fold_conversation_session_id,
    fold_payload_session_id,
)
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    CURSOR_SESSION_MAP_DIR_NAME,
    resolve_ambient_session_id,
)
from yoke_harness.hooks.identity_runtime import is_cursor


def resolved_session_id(payload: dict[str, Any]) -> Optional[str]:
    """Fold ``payload.session_id`` through the conversation map, else ambient.

    A mapped conversation becomes the recorded session. An unmapped
    conversation yields empty — stamp that empty value; empty beats wrong. A
    non-conversation id (Claude/Codex) is returned raw. Absent
    ``session_id`` falls through to the ambient chain.
    """
    try:
        home = machine_config.yoke_home()
        map_dir = home / CURSOR_SESSION_MAP_DIR_NAME
        folded = fold_payload_session_id(payload, map_dir)
        if folded is not None:
            return folded
        return resolve_ambient_session_id(
            home / ANCHORS_DIR_NAME,
            os.environ,
            cursor_map_dir=map_dir,
        )
    except Exception:  # noqa: BLE001 — hook path must never raise
        return None


def _resolved_container_session_id(
    payload: dict[str, Any],
    executor: str,
) -> Optional[str]:
    """Fold Cursor's transcript-derived container channel on the client."""
    if not is_cursor(executor):
        return None
    try:
        raw = container_session_id_from_evidence(payload)
        if not raw:
            return None
        home = machine_config.yoke_home()
        return fold_conversation_session_id(
            raw,
            home / CURSOR_SESSION_MAP_DIR_NAME,
        )
    except Exception:  # noqa: BLE001 — hook path must never raise
        return None


def stamp_hook_stdin(
    stdin_data: str,
    payload: dict[str, Any],
    executor: str = "",
) -> str:
    """Stamp the folded payload and Cursor-container session identities.

    Mutates *payload* in place. Rewrites stdin JSON when the stamp
    replaces a conversation id, clears an unmapped conversation id, or fills
    an omitted id.
    """
    changed = False
    container_session_id = _resolved_container_session_id(payload, executor)
    if container_session_id is not None and (
        payload.get("container_session_id") != container_session_id
    ):
        payload["container_session_id"] = container_session_id
        changed = True
    session_id = resolved_session_id(payload)
    current = payload.get("session_id")
    if session_id is not None and not (
        isinstance(current, str) and current.strip() == session_id
    ):
        payload["session_id"] = session_id
        changed = True
    if session_id:
        payload["identity_stamped"] = True
        changed = True
    if not changed:
        return stdin_data
    try:
        return json.dumps(payload)
    except (TypeError, ValueError):
        return stdin_data


def record_then_stamp(
    payload: dict[str, Any],
    stdin_data: str,
    executor: str,
    event_name: str,
) -> str:
    """Record the Cursor conversation pairing, then stamp session identity."""
    from yoke_core.domain.session_ambient_identity import is_hook_replay
    from yoke_harness.hooks import cursor_session_map

    if is_hook_replay():
        return stamp_hook_stdin(stdin_data, payload, executor)
    try:
        from runtime.harness.cursor.cursor_worktree_session_fold import (
            record_remount_conversation_session,
        )

        record_remount_conversation_session(payload)
    except Exception:  # noqa: BLE001 — remount bookkeeping must not break hooks
        pass
    cursor_session_map.record_from_hook_payload(payload, executor, event_name)
    return stamp_hook_stdin(stdin_data, payload, executor)


__all__ = [
    "record_then_stamp",
    "resolved_session_id",
    "stamp_hook_stdin",
]
