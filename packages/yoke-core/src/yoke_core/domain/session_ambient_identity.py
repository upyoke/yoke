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
from typing import Any, Mapping, Optional

from yoke_contracts.session_identity import (
    AMBIENT_ENV_VARS,
    AMBIENT_RESOLUTION_FAILED,
)


def resolve_env_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Return the first non-empty session id from the canonical env chain."""
    source = os.environ if env is None else env
    for name in AMBIENT_ENV_VARS:
        value = source.get(name)
        if value:
            return value
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
        return value
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
    """Return payload ``session_id`` when set, else the canonical ambient chain."""
    raw = payload.get("session_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return resolve_ambient_session_id(env) or ""


__all__ = [
    "AMBIENT_ENV_VARS",
    "AMBIENT_RESOLUTION_FAILED",
    "resolve_ambient_session_id",
    "resolve_env_session_id",
    "session_id_from_hook_payload",
]
