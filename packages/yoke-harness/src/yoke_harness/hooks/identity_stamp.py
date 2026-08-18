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
from yoke_contracts.cursor_remount_expect import (
    REMOUNT_OBSERVING,
    REMOUNT_REFUSED,
    REMOUNT_REFUSAL_PAYLOAD_FIELD,
    is_remount_observation_event,
)
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
    *,
    forced_session_id: Optional[str] = None,
    forced_container_session_id: Optional[str] = None,
) -> str:
    """Stamp the folded payload and Cursor-container session identities.

    Mutates *payload* in place. Rewrites stdin JSON when the stamp
    replaces a conversation id, clears an unmapped conversation id, or fills
    an omitted id.
    """
    changed = False
    container_session_id = (
        forced_container_session_id
        if forced_container_session_id is not None
        else _resolved_container_session_id(payload, executor)
    )
    if container_session_id is not None and (
        payload.get("container_session_id") != container_session_id
    ):
        payload["container_session_id"] = container_session_id
        changed = True
    session_id = (
        forced_session_id
        if forced_session_id is not None
        else resolved_session_id(payload)
    )
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
    from yoke_contracts.payload_session_fold import is_hook_replay
    from yoke_harness.hooks import cursor_session_map

    if is_hook_replay():
        return stamp_hook_stdin(stdin_data, payload, executor)
    worktree_fold = cursor_session_map.record_from_hook_payload(
        payload,
        executor,
        event_name,
    )
    if worktree_fold is not None:
        decision = worktree_fold.remount
        if decision.outcome == REMOUNT_OBSERVING and is_remount_observation_event(
            event_name
        ):
            return stamp_hook_stdin(
                stdin_data,
                payload,
                executor,
                forced_session_id=decision.holder_session_id,
                forced_container_session_id=decision.holder_session_id,
            )
        if decision.outcome in {REMOUNT_OBSERVING, REMOUNT_REFUSED}:
            payload[REMOUNT_REFUSAL_PAYLOAD_FIELD] = {
                "arriving_conversation_id": decision.arriving_conversation_id,
                "holder_conversation_id": decision.holder_conversation_id,
                "holder_session_id": decision.holder_session_id,
                "lane": worktree_fold.lane,
                "outcome": decision.outcome,
            }
            return stamp_hook_stdin(
                stdin_data,
                payload,
                executor,
                forced_session_id=decision.arriving_conversation_id,
                forced_container_session_id=decision.arriving_conversation_id,
            )
    try:
        conv = payload.get("conversation_id") or payload.get("session_id")
        if isinstance(conv, str) and conv:
            from yoke_cli.config import machine_config
            from yoke_contracts.cursor_session_map import (
                CURSOR_SESSION_MAP_DIR_NAME,
                linked_worktree_lane_name,
                recorded_session_id_for_conversation,
            )

            existing = recorded_session_id_for_conversation(
                machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME,
                conv,
            )
            if not existing:
                roots = payload.get("workspace_roots")
                workspace = ""
                if isinstance(roots, list) and roots and isinstance(roots[0], str):
                    workspace = roots[0]
                elif isinstance(payload.get("cwd"), str):
                    workspace = payload["cwd"]
                if not linked_worktree_lane_name(workspace):
                    cursor_session_map.record_conversation_session(conv, conv)
                    cursor_session_map.refresh_remount_expect(conv)
    except Exception:  # noqa: BLE001 — remount bookkeeping must not break hooks
        pass
    return stamp_hook_stdin(stdin_data, payload, executor)


__all__ = [
    "record_then_stamp",
    "resolved_session_id",
    "stamp_hook_stdin",
]
