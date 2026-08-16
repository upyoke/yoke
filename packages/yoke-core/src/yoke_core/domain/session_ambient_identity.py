"""Canonical ambient session-identity resolution.

Single owner of the ambient chain every Yoke surface uses to answer
"which harness session is this process running under?":

1. **Env chain (fast path):** ``YOKE_SESSION_ID`` →
   ``CLAUDE_SESSION_ID`` → ``CODEX_THREAD_ID``. Populated by harnesses
   that stamp identity into the environment (the desktop harness
   prepends a per-command export; Codex exports at SessionStart).
2. **Process-anchor ancestry walk:** the hook-written registry under
   ``<machine-home>/session-anchors/`` maps the per-session harness
   agent pid to its session id, so any shell spawned by that harness
   self-identifies with zero agent involvement even when no env stamp
   was delivered (:mod:`yoke_core.domain.session_process_anchors`).
3. **Cursor conversation mapping:** the hook-written pairing under
   ``<machine-home>/cursor-session-map/`` resolves the conversation id a
   Cursor shell carries to the top-level session Yoke registered for it
   (:mod:`yoke_contracts.cursor_session_map`) — the lane for a harness
   that stamps nothing step 1 reads and hosts every conversation in one
   process, so step 2 can record no anchor.
4. ``None`` — no ambient identity. Mutating dispatch surfaces treat
   this as a Yoke infrastructure gap (``actor_session_missing``), not
   a condition for agents to work around.

Consumers: the function-call dispatcher's identity binder
(:mod:`yoke_core.domain.yoke_function_actor_identity`), the CLI
envelope builder (:mod:`yoke_core.api.service_client_shared_session_resolver`),
and the hook helpers. Per-command env stamping demotes to a fast path of
this chain rather than the only identity source.
"""

from __future__ import annotations

import os
from typing import Any, List, Mapping, Optional

from yoke_contracts.payload_session_fold import (
    HOOK_REPLAY_ENV,
    is_conversation_shaped_session_id,
    is_hook_replay,
)
from yoke_contracts.session_identity import (
    AMBIENT_ENV_VARS,
    AMBIENT_RESOLUTION_FAILED,
)


def fold_raw_identity(
    raw: object,
    *,
    map_dir=None,
    env: Optional[Mapping[str, str]] = None,
    conversation_aliases: tuple = (),
) -> str:
    """Fold one identity channel through the shared conversation-to-session map.

    Every ambient channel (payload session_id, env vars, transcript /
    container ids) must call this helper. A conversation-shaped id never
    returns raw.
    """
    from yoke_contracts.cursor_session_map import (
        CURSOR_CONVERSATION_ENV_VAR,
        CURSOR_SESSION_MAP_DIR_NAME,
    )
    from yoke_contracts.payload_session_fold import fold_conversation_session_id
    from yoke_core.domain import machine_config

    if not isinstance(raw, str) or not raw.strip():
        return ""
    raw = raw.strip()
    directory = map_dir
    if directory is None:
        directory = machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME
    mapped = fold_conversation_session_id(raw, directory)
    if mapped:
        return mapped
    source = os.environ if env is None else env
    aliases = list(conversation_aliases)
    env_cid = source.get(CURSOR_CONVERSATION_ENV_VAR)
    if isinstance(env_cid, str) and env_cid.strip():
        aliases.append(env_cid.strip())
    if any(isinstance(alias, str) and alias.strip() == raw for alias in aliases):
        return ""
    return raw


def consult_identity_channels(
    payload: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
) -> List[dict[str, str]]:
    """Return each identity channel consulted and its folded outcome."""
    from yoke_contracts.session_identity import AMBIENT_ENV_VARS

    source = os.environ if env is None else env
    payload = payload or {}
    channels: List[dict[str, str]] = []
    raw_payload = payload.get("session_id")
    folded_payload = fold_raw_identity(
        raw_payload,
        env=source,
        conversation_aliases=(
            payload.get("conversation_id"),
            payload.get("remapped_conversation_id"),
        ),
    )
    channels.append({
        "channel": "payload_session_id",
        "raw": raw_payload if isinstance(raw_payload, str) else "",
        "resolved": folded_payload,
    })
    for name in AMBIENT_ENV_VARS:
        value = source.get(name, "")
        channels.append({
            "channel": f"env:{name}",
            "raw": value or "",
            "resolved": fold_raw_identity(value, env=source) if value else "",
        })
    try:
        from yoke_core.domain.session_process_anchors import anchors_dir
        from yoke_contracts.session_identity import resolve_session_from_ancestry

        ancestry = resolve_session_from_ancestry(anchors_dir()) or ""
    except Exception:
        ancestry = ""
    channels.append({
        "channel": "process_anchor",
        "raw": ancestry,
        "resolved": fold_raw_identity(ancestry, env=source) if ancestry else "",
    })
    return channels


def resolve_env_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the first non-empty session id from the canonical env chain."""
    source = os.environ if env is None else env
    for name in AMBIENT_ENV_VARS:
        value = source.get(name)
        folded = fold_raw_identity(value, env=source)
        if folded:
            return folded
    return None


def resolve_ambient_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve ambient session identity: env chain, ancestry, hook mapping.

    Returns ``None`` when no source yields an id. Never raises.
    """
    value = resolve_env_session_id(env)
    if value:
        return value
    from yoke_core.domain.session_process_anchors import (
        resolve_session_from_ancestry,
    )

    value = resolve_session_from_ancestry()
    if value:
        return fold_raw_identity(value, env=env) or None
    from yoke_contracts.cursor_session_map import (
        CURSOR_SESSION_MAP_DIR_NAME,
        resolve_mapped_session_id,
    )
    from yoke_core.domain import machine_config

    return resolve_mapped_session_id(
        machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME, env,
    )


def session_id_from_hook_payload(
    payload: Mapping[str, Any],
    env: Optional[Mapping[str, str]] = None,
) -> str:
    """Fold payload ``session_id`` through the conversation map, else ambient.

    A mapped conversation becomes the recorded session. An unmapped
    conversation yields empty so the write guard reports identity
    failure, not a foreign lane. A non-conversation id is returned raw.
    A client-stamped id is authoritative across relay even when it
    equals a conversation alias.
    """
    if payload.get("identity_stamped") is True:
        stamped = payload.get("session_id")
        if isinstance(stamped, str) and stamped.strip():
            return stamped.strip()
    folded = fold_raw_identity(
        payload.get("session_id"),
        env=env,
        conversation_aliases=(
            payload.get("conversation_id"),
            payload.get("remapped_conversation_id"),
        ),
    )
    if folded:
        return folded
    if is_conversation_shaped_session_id(payload, env=env):
        return ""
    return resolve_ambient_session_id(env) or ""


def contested_anchor_session_ids() -> List[str]:
    """Session ids recorded as co-tenants on any live process anchor."""
    try:
        import json
        from yoke_core.domain.session_process_anchors import anchors_dir

        found: List[str] = []
        for path in anchors_dir().glob("*.json"):
            rec = json.loads(path.read_text())
            for item in rec.get("contending_session_ids") or ():
                if item:
                    found.append(str(item))
        return sorted(set(found))
    except Exception:
        return []


def _public_channel(channel: str) -> str:
    """Agent-facing label that does not teach env-var self-bootstrap."""
    if not channel.startswith("env:"):
        return channel
    name = channel[4:]
    if name == AMBIENT_ENV_VARS[0]:
        return "env:session"
    if name == AMBIENT_ENV_VARS[1]:
        return "env:claude"
    if name == AMBIENT_ENV_VARS[2]:
        return "env:codex"
    return "env:other"


def format_actor_session_missing(function_id: str) -> str:
    """Error text for actor_session_missing naming every consulted channel."""
    named = ", ".join(
        f"{_public_channel(row['channel'])}={row['resolved'] or row['raw'] or 'empty'}"
        for row in consult_identity_channels()
    )
    contested = contested_anchor_session_ids()
    extra = f" contested_anchors={contested}" if contested else ""
    return (
        f"mutating function {function_id!r} could not resolve an ambient "
        "harness session for this process. "
        f"Consulted: {named}.{extra} "
        "This is a Yoke infrastructure gap (session registration or "
        "process-anchor resolution failed), not something to work around "
        "— file a field-note if you can, otherwise report it to the "
        "operator. Operator-debug only: an explicit session id "
        "(--session-id) overrides ambient resolution."
    )


__all__ = [
    "AMBIENT_ENV_VARS",
    "AMBIENT_RESOLUTION_FAILED",
    "HOOK_REPLAY_ENV",
    "consult_identity_channels",
    "contested_anchor_session_ids",
    "fold_raw_identity",
    "format_actor_session_missing",
    "is_conversation_shaped_session_id",
    "is_hook_replay",
    "resolve_ambient_session_id",
    "resolve_env_session_id",
    "session_id_from_hook_payload",
]
