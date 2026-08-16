"""Best-effort Cursor conversation-to-session recording from hook processes.

Binds the shared body in :mod:`yoke_contracts.cursor_session_map` to the
product CLI's machine home, the same split (and for the same reason) as
:mod:`yoke_harness.hooks.identity_anchor`. Hook processes are the only
place both ids are visible at once, so they are the only place the pairing
can be written; every later shell is a reader.
"""

from __future__ import annotations

import os

from yoke_cli.config import machine_config
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    container_session_id_from_evidence,
    prune_stale_conversation_sessions,
    record_conversation_session as _record_conversation_session,
    resolve_container_from_subagent_transcript_layout,
)
from yoke_contracts.payload_session_fold import fold_conversation_session_id
from yoke_harness.hooks.identity_runtime import is_cursor


def _map_dir():
    return machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME


def record_conversation_session(conversation_id: str, session_id: str) -> None:
    """Record that ``conversation_id`` belongs to ``session_id``."""
    _record_conversation_session(conversation_id, session_id, _map_dir())


def record_from_hook_payload(
    payload: dict, executor: str, event_name: str = "",
) -> None:
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

    The first client hook establishes the container when no evidence
    names a different parent, worktree remap is empty, the on-disk
    subagent transcript layout is empty, and the payload is top-level
    shaped. Cursor leaves the transcript path empty through a fresh
    session’s first events, so SessionStart-only establish left the
    first write-shaped Shell unidentified.

    A later sessionStart (or any write) that would map a conversation onto
    itself must not erase an existing worktree/subagent fold: Cursor can
    re-fire sessionStart without ``workspace_roots``, and the identity
    fallback would otherwise clobber the claim-holder alias.

    When the payload adapter has already folded ``session_id`` onto the
    container, the child id survives on ``subagent_session_id`` /
    ``remapped_conversation_id`` / ``conversation_id`` / the Cursor env
    var — each distinct child alias is recorded so shells that only carry
    the child conversation id still resolve.
    """
    if not is_cursor(executor):
        return
    try:
        conversation_id = payload.get("conversation_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            conversation_id = payload.get("session_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            return
        raw_container = container_session_id_from_evidence(payload)
        if raw_container:
            container = fold_conversation_session_id(
                raw_container,
                _map_dir(),
            )
            if not container:
                if raw_container == conversation_id:
                    if _top_level_shaped(payload, conversation_id):
                        container = conversation_id
                else:
                    container = raw_container
        else:
            container = _worktree_remap_container(payload)
            if not container:
                container = resolve_container_from_subagent_transcript_layout(
                    conversation_id,
                )
            if not container and _top_level_shaped(payload, conversation_id):
                container = (
                    fold_conversation_session_id(
                        conversation_id,
                        _map_dir(),
                    )
                    or conversation_id
                )
        if not container:
            return
        aliases = {conversation_id}
        for key in (
            "conversation_id",
            "subagent_session_id",
            "remapped_conversation_id",
        ):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                aliases.add(value.strip())
        env_cid = (os.environ.get(CURSOR_CONVERSATION_ENV_VAR, "") or "").strip()
        if env_cid:
            aliases.add(env_cid)
        for alias in aliases:
            record_conversation_session(alias, container)
    except Exception:  # noqa: BLE001 — bookkeeping must not break a hook
        return


def _top_level_shaped(payload: dict, conversation_id: str) -> bool:
    """True when this payload is the top-level conversation, not a child."""
    session_id = payload.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id == conversation_id
    return True


def _worktree_remap_container(payload: dict) -> str:
    """Alias a linked-worktree remount onto its claim-holder session.

    Client hooks must not import ``yoke_core`` (package boundary). Lane
    parsing stays in contracts; holder lookup rides the function-call
    dispatcher over the active transport.
    """
    from yoke_contracts.cursor_session_map import linked_worktree_lane_name

    roots = payload.get("workspace_roots")
    workspace = ""
    if isinstance(roots, list) and roots and isinstance(roots[0], str):
        workspace = roots[0]
    elif isinstance(payload.get("cwd"), str):
        workspace = payload["cwd"]
    lane = linked_worktree_lane_name(workspace)
    if not lane:
        return ""
    try:
        from yoke_cli.commands._helpers import (
            ensure_handlers_loaded,
            item_target,
        )
        from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

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
    if not isinstance(session_id, str) or not session_id:
        return ""
    own = payload.get("session_id") or payload.get("conversation_id") or ""
    if isinstance(own, str) and own and own == session_id:
        return ""
    return session_id


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
