"""Fold Cursor workspace remaps into the claim-holder harness session.

When Cursor remounts a chat onto a linked Yoke worktree (``move_agent_to_root``
or equivalent), it often assigns a new conversation id under a new project
path while work claims stay on the prior container session. This module
resolves that container from the worktree lane name → active item claim
holder, then observes the remount-expect receipt across one hook boundary.
The new conversation aliases only when the holder conversation stayed quiet;
folder occupancy alone is not enough.

Never raises — a wrong fold is worse than a missing one. Empty string means
"no evidence; caller keeps the payload's own id."
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from yoke_contracts.cursor_remount_expect import (
    REMOUNT_CONTINUITY,
    REMOUNT_OBSERVING,
    REMOUNT_REFUSED,
    REMOUNT_REFUSAL_PAYLOAD_FIELD,
    is_remount_observation_event,
    observe_remount_candidate,
)


def workspace_path_from_payload(payload: Mapping[str, Any]) -> str:
    """Return the Cursor workspace path named by the hook payload or env."""
    import os

    roots = payload.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]:
        return roots[0]
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    for env_var in ("CURSOR_PROJECT_DIR", "YOKE_ROOT"):
        value = os.environ.get(env_var, "")
        if value:
            return value
    return ""


def _cursor_map_dir(map_dir=None):
    if map_dir is not None:
        return map_dir
    from yoke_cli.config import machine_config
    from yoke_contracts.cursor_session_map import CURSOR_SESSION_MAP_DIR_NAME

    return machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME


def resolve_worktree_remap_container(
    payload: Mapping[str, Any],
    *,
    holder_lookup=None,
    map_dir=None,
) -> str:
    """Return the claim-holder session for a linked-worktree workspace.

    ``holder_lookup`` is injectable for tests: ``callable(lane: str) -> str``.
    Default lookup uses ``claims.work.holder_get`` over the active transport
    so https control planes work from client hook processes.

    A foreign holder is returned only when a live remount-expect receipt
    exists and its holder conversation stays quiet across the candidate's
    first hook boundary. Folder occupancy alone is not enough.
    """
    from yoke_contracts.cursor_session_map import linked_worktree_lane_name

    workspace = workspace_path_from_payload(payload)
    lane = linked_worktree_lane_name(workspace)
    if not lane:
        return ""
    lookup = holder_lookup or _holder_session_for_lane
    try:
        holder = lookup(lane)
    except Exception:  # noqa: BLE001 — fold must never break a hook
        return ""
    if not isinstance(holder, str) or not holder:
        return ""
    own = payload.get("session_id") or payload.get("conversation_id") or ""
    if isinstance(own, str) and own and own == holder:
        return ""
    try:
        target = _cursor_map_dir(map_dir)
    except Exception:  # noqa: BLE001
        return ""
    conversation_id = payload.get("conversation_id") or own
    if not isinstance(conversation_id, str) or not conversation_id:
        return ""
    decision = observe_remount_candidate(target, holder, conversation_id)
    if decision.outcome == REMOUNT_CONTINUITY:
        from yoke_contracts.cursor_session_map import record_conversation_session

        if not record_conversation_session(conversation_id, holder, target):
            return ""
        return holder
    event_name = str(payload.get("hook_event_name") or "")
    if decision.outcome == REMOUNT_OBSERVING and is_remount_observation_event(
        event_name
    ):
        # SessionStart establishes the observation point but grants no durable
        # map entry. The next hook must prove the prior conversation stayed
        # quiet before the worktree conversation gains write authority.
        return holder
    if decision.outcome in {REMOUNT_OBSERVING, REMOUNT_REFUSED} and isinstance(
        payload,
        dict,
    ):
        payload[REMOUNT_REFUSAL_PAYLOAD_FIELD] = {
            "arriving_conversation_id": decision.arriving_conversation_id,
            "holder_conversation_id": decision.holder_conversation_id,
            "holder_session_id": decision.holder_session_id,
            "lane": lane,
            "outcome": decision.outcome,
        }
    return ""


def _holder_session_for_lane(lane: str) -> str:
    """Resolve the active work-claim holder session for a worktree lane name."""
    # Prefer in-process claim read when a local control-plane DB is reachable.
    try:
        from yoke_core.domain import db_helpers
        from yoke_core.domain.item_worktree_resolution import (
            resolve_item_id_by_worktree_name,
        )
        from yoke_core.domain.yoke_function_dispatch_claims import (
            who_claims_for_item,
        )

        with db_helpers.connect() as conn:
            item_id = resolve_item_id_by_worktree_name(conn, lane)
        if item_id is not None:
            row = who_claims_for_item(int(item_id))
            if isinstance(row, dict):
                session_id = row.get("session_id")
                if isinstance(session_id, str) and session_id:
                    return session_id
    except Exception:  # noqa: BLE001 — fall through to transport
        pass
    return _holder_session_via_dispatcher(lane)


def _holder_session_via_dispatcher(lane: str) -> str:
    """HTTPS-safe holder lookup through the function-call dispatcher."""
    try:
        from yoke_cli.commands._helpers import (
            ensure_handlers_loaded,
            item_target,
        )
        from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
    except Exception:
        return ""
    try:
        ensure_handlers_loaded()
        response = call_dispatcher(
            function_id="claims.work.holder_get",
            target=item_target("item", lane, None),
            payload={},
            actor=build_actor(session_id=None),
            timeout_s=5.0,
        )
    except Exception:  # noqa: BLE001
        return ""
    if not getattr(response, "success", False):
        return ""
    result = getattr(response, "result", None) or {}
    holder = result.get("holder") if isinstance(result, dict) else None
    if not isinstance(holder, dict):
        return ""
    session_id = holder.get("session_id")
    return session_id if isinstance(session_id, str) else ""


def record_remount_conversation_session(
    payload: Mapping[str, Any],
    *,
    conversation_id: Optional[str] = None,
    holder_lookup=None,
    record=None,
    map_dir=None,
) -> str:
    """Write conversation→holder pairing when a remount receipt is live.

    ``record`` is injectable: ``callable(conversation_id, session_id)``.
    Default writes the client cursor-session-map. Returns the holder
    session, or empty when no pairing could be recorded. A foreign
    holder requires consuming a live remount-expect receipt.
    """
    holder = resolve_worktree_remap_container(
        payload,
        holder_lookup=holder_lookup,
        map_dir=map_dir,
    )
    conv = (
        conversation_id or payload.get("conversation_id") or payload.get("session_id")
    )
    if not isinstance(conv, str) or not conv:
        return holder
    if not holder:
        from yoke_contracts.cursor_session_map import linked_worktree_lane_name

        lane = linked_worktree_lane_name(workspace_path_from_payload(payload))
        lookup = holder_lookup or _holder_session_for_lane
        try:
            found = lookup(lane) if lane else ""
        except Exception:  # noqa: BLE001
            found = ""
        if found != conv:
            return ""
        holder = found
    writer = record
    if writer is None:
        from yoke_harness.hooks.cursor_session_map import record_conversation_session

        writer = record_conversation_session
    try:
        writer(conv, holder)
    except Exception:  # noqa: BLE001 — remount must never break the chat
        return holder
    return holder


__all__ = [
    "record_remount_conversation_session",
    "resolve_worktree_remap_container",
    "workspace_path_from_payload",
]
