"""Canonical ambient session-identity resolution.

Single owner of the ambient chain every Yoke surface uses to answer
"which harness session is this process running under?":

0. **Yoke's own stamp:** ``YOKE_SESSION_ID``, the operator override an
   explicit ``--session-id`` propagates, outranks everything below.
1. **The owning harness family** (:mod:`yoke_contracts.harness_family_identity`),
   read from the process tree because nothing there is inherited, scopes
   every step below it: only the family this process actually runs under
   may answer, so a variable an outer harness exported into a nested one
   never does.
2. **Env chain:** that family's own session variables — populated by
   harnesses that stamp identity into the environment (the desktop
   harness prepends a per-command export; Codex exports at SessionStart).
3. **Process-anchor ancestry walk:** the hook-written registry under
   ``<machine-home>/session-anchors/`` maps the per-session harness
   agent pid to its session id, so any shell spawned by that harness
   self-identifies with zero agent involvement even when no env stamp
   was delivered (:mod:`yoke_core.domain.session_process_anchors`).
4. **Cursor conversation mapping:** the hook-written pairing under
   ``<machine-home>/cursor-session-map/`` resolves the conversation id a
   Cursor shell carries to the top-level session Yoke registered for it
   (:mod:`yoke_contracts.cursor_session_map`) — the lane for a harness
   that stamps nothing step 1 reads and hosts every conversation in one
   process, so step 2 can record no anchor.
5. ``None`` — no ambient identity. Mutating dispatch surfaces treat
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
from yoke_contracts.harness_family_identity import (
    CURSOR_FAMILY,
    HARNESS_FAMILY_ENV_VARS,
    YOKE_SESSION_ENV_VAR,
    nearest_harness_family,
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
    channels.append({
        "channel": "process_family",
        "raw": nearest_harness_family() or "",
        "resolved": "",
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


def _owning_family_session_id(
    family: str, source: Mapping[str, str],
) -> Optional[str]:
    """Session id from the channels ``family`` stamps into its own processes.

    Falls to ``None`` rather than to another family's channel: where the
    only remaining candidate is a variable a *different* harness exported
    into this process, reporting no identity is the correct answer.
    """
    from yoke_contracts.cursor_session_map import (
        CURSOR_SESSION_MAP_DIR_NAME,
        resolve_mapped_session_id,
    )
    from yoke_core.domain import machine_config
    from yoke_core.domain.session_process_anchors import (
        resolve_session_from_ancestry,
    )

    for name in HARNESS_FAMILY_ENV_VARS.get(family, ()):
        folded = fold_raw_identity(source.get(name), env=source)
        if folded:
            return folded
    anchored = resolve_session_from_ancestry()
    if anchored:
        return fold_raw_identity(anchored, env=source) or None
    if family != CURSOR_FAMILY:
        return None
    return resolve_mapped_session_id(
        machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME, source,
    )


def resolve_ambient_session_id(
    env: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Resolve ambient session identity for the calling process.

    Yoke's own stamp wins outright. Otherwise the harness family the
    process tree names decides which channels may answer. The
    family-blind chain below runs only for a process with no harness
    ancestor — an operator terminal, CI, or a process reparented after
    its harness exited — where an inherited variable is the best
    evidence available. Returns ``None`` when no source yields an id.
    Never raises.
    """
    source = os.environ if env is None else env
    explicit = fold_raw_identity(source.get(YOKE_SESSION_ENV_VAR), env=source)
    if explicit:
        return explicit
    family = nearest_harness_family()
    if family is not None:
        return _owning_family_session_id(family, source)
    value = resolve_env_session_id(source)
    if value:
        return value
    from yoke_core.domain.session_process_anchors import (
        resolve_session_from_ancestry,
    )

    value = resolve_session_from_ancestry()
    if value:
        return fold_raw_identity(value, env=source) or None
    from yoke_contracts.cursor_session_map import (
        CURSOR_SESSION_MAP_DIR_NAME,
        resolve_mapped_session_id,
    )
    from yoke_core.domain import machine_config

    return resolve_mapped_session_id(
        machine_config.yoke_home() / CURSOR_SESSION_MAP_DIR_NAME, source,
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
    """Agent-facing label that does not teach env-var self-bootstrap.

    Derived from the variable rather than its position in the chain, so
    a chain that grows relabels itself instead of silently shifting every
    label one slot along. ``CODEX_SESSION_ID`` and ``CODEX_THREAD_ID``
    stay distinguishable because parent-versus-child is the whole reason
    a Codex subagent's diagnostics are worth reading.

    The family is what remains after the trailing role suffix, not the
    first underscore-delimited word, because a harness may spell its
    family with an underscore of its own (``CLAUDE_CODE_SESSION_ID``).
    """
    if not channel.startswith("env:"):
        return channel
    name = channel[4:]
    if name not in AMBIENT_ENV_VARS:
        return "env:other"
    for suffix, role in (("_THREAD_ID", "-thread"), ("_SESSION_ID", "")):
        if name.endswith(suffix):
            family = name[: -len(suffix)].lower().replace("_", "-")
            return "env:session" if family == "yoke" else f"env:{family}{role}"
    return "env:other"


def format_actor_session_missing(function_id: str) -> str:
    """Error text for actor_session_missing naming every consulted channel."""
    from yoke_core.domain.session_missing_refusal import format_session_missing

    named = ", ".join(
        f"{_public_channel(row['channel'])}={row['resolved'] or row['raw'] or 'empty'}"
        for row in consult_identity_channels()
    )
    return format_session_missing(
        function_id,
        channels=named,
        contested=contested_anchor_session_ids() or None,
        harness_family=nearest_harness_family() or "",
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
