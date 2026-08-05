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
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    container_session_id_from_evidence,
    prune_stale_conversation_sessions,
    record_conversation_session as _record_conversation_session,
    resolve_mapped_session_id,
)
from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT
from yoke_harness.hooks.identity_runtime import is_cursor


def _map_dir():
    return machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME


def record_conversation_session(conversation_id: str, session_id: str) -> None:
    """Record that ``conversation_id`` belongs to ``session_id``."""
    _record_conversation_session(conversation_id, session_id, _map_dir())


def _existing_fold_container(conversation_id: str) -> str:
    """Return a prior non-identity map target for ``conversation_id``, else ``\"\"``."""
    existing = resolve_mapped_session_id(
        _map_dir(),
        {CURSOR_CONVERSATION_ENV_VAR: conversation_id},
    )
    if (
        isinstance(existing, str)
        and existing
        and existing != conversation_id
    ):
        return existing
    return ""


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

    Session start is the one event that needs no evidence. Cursor leaves
    the transcript path empty through a fresh session's first events, so
    without this the session's FIRST command — the one likeliest to be a
    ``/yoke`` entrypoint — resolves to nothing. It fires once for the
    top-level session, which is the same basis on which registration
    already treats that id as the container; a sub-conversation carries
    ``parent_conversation_id``, which the evidence rule reads first.

    A later sessionStart (or any write) that would map a conversation onto
    itself must not erase an existing worktree/subagent fold: Cursor can
    re-fire sessionStart without ``workspace_roots``, and the identity
    fallback would otherwise clobber the claim-holder alias.
    """
    if not is_cursor(executor):
        return
    try:
        conversation_id = payload.get("session_id")
        if not isinstance(conversation_id, str) or not conversation_id:
            return
        container = container_session_id_from_evidence(payload)
        if not container:
            container = _worktree_remap_container(payload)
        if not container and event_name == SESSION_START_EVENT:
            container = conversation_id
        if container == conversation_id:
            folded = _existing_fold_container(conversation_id)
            if folded:
                container = folded
        if container:
            record_conversation_session(conversation_id, container)
    except Exception:  # noqa: BLE001 — bookkeeping must not break a hook
        return


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
