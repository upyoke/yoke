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
3. ``None`` — no ambient identity. Mutating dispatch surfaces treat
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
from typing import Mapping, Optional, Tuple


AMBIENT_ENV_VARS: Tuple[str, ...] = (
    "YOKE_SESSION_ID",
    "CLAUDE_SESSION_ID",
    "CODEX_THREAD_ID",
)

# One denial sentence for every surface that requires a session and found
# none. Names the infrastructure-gap framing and the operator-debug
# override; deliberately does NOT teach env-var self-bootstrap.
AMBIENT_RESOLUTION_FAILED = (
    "ambient session identity could not be resolved (env chain, then the "
    "hook-written process-anchor registry) — this is a Yoke "
    "infrastructure gap, not something to work around; file a field-note "
    "if you can, otherwise report it to the operator. Operator-debug "
    "override: --session-id."
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
    """Resolve ambient session identity: env chain, then ancestry registry.

    Returns ``None`` when neither source yields an id. Never raises.
    """
    value = resolve_env_session_id(env)
    if value:
        return value
    from yoke_core.domain.session_process_anchors import (
        resolve_session_from_ancestry,
    )

    return resolve_session_from_ancestry()


__all__ = [
    "AMBIENT_ENV_VARS",
    "AMBIENT_RESOLUTION_FAILED",
    "resolve_ambient_session_id",
    "resolve_env_session_id",
]
