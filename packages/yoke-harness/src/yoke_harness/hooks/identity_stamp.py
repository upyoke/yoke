"""Stamp hook payloads with canonical ambient session identity.

The client hook process is the only side that can see this machine's
env chain, process-anchor registry, and cursor-session-map. Recording
the Cursor conversation pairing must happen on the original payload
(the conversation id still lives on ``session_id``); stamping the
resolved Yoke session onto ``payload.session_id`` happens after that
so the lint chain never re-resolves.
"""

from __future__ import annotations

import json
import os
from typing import Any

from yoke_cli.config import machine_config
from yoke_contracts.payload_session_fold import fold_payload_session_id
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    CURSOR_SESSION_MAP_DIR_NAME,
    resolve_ambient_session_id,
)


def resolved_session_id(payload: dict[str, Any]) -> str:
    """Fold ``payload.session_id`` through the conversation map, else ambient.

    A mapped conversation becomes the recorded session. An unmapped
    conversation yields empty — stamp nothing; empty beats wrong. A
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
        ) or ""
    except Exception:  # noqa: BLE001 — hook path must never raise
        return ""


def stamp_hook_stdin(stdin_data: str, payload: dict[str, Any]) -> str:
    """Stamp ``payload.session_id`` with the folded or ambient session.

    Mutates *payload* in place. Rewrites stdin JSON when the stamp
    replaces a conversation id or fills an omitted id. An unmapped
    conversation leaves the payload unchanged (stamp nothing).
    """
    session_id = resolved_session_id(payload)
    if not session_id:
        return stdin_data
    current = payload.get("session_id")
    if isinstance(current, str) and current.strip() == session_id:
        return stdin_data
    payload["session_id"] = session_id
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
    from yoke_harness.hooks import cursor_session_map

    cursor_session_map.record_from_hook_payload(payload, executor, event_name)
    return stamp_hook_stdin(stdin_data, payload)


__all__ = [
    "record_then_stamp",
    "resolved_session_id",
    "stamp_hook_stdin",
]
