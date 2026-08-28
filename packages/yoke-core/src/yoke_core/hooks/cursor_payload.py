"""Cursor hook payload parsing and canonicalization.

Owns the input-side surface of the Cursor hook chain. Cursor delivers one
JSON document on stdin per hook invocation; this module parses it and
normalizes the Cursor-native shape into the canonical payload fields the
shared runner and policy chains expect:

- ``tool_name``: Cursor's shell tool is named ``Shell``; the universal
  chains are keyed on ``Bash``. ``beforeShellExecution`` /
  ``afterShellExecution`` payloads carry no ``tool_name`` at all — they
  carry a top-level ``command`` — so the parser synthesizes
  ``tool_name="Bash"`` and ``tool_input={"command": ...}`` for them.
- Session identity: Cursor exports **no session-id environment variable**.
  Every payload carries ``session_id`` and ``conversation_id`` (equal
  values). Subagent activity arrives under the *subagent's own*
  ``session_id``; the top-level session is recovered from the
  ``CURSOR_TRANSCRIPT_PATH`` environment variable, which points at the
  top-level session's transcript in every hook process — including hooks
  fired for subagent activity — and whose basename stem is the top-level
  session id. Yoke's container model registers only the top-level session,
  so ``resolve_container_session_id`` is the identity every control-plane
  write should attribute to. The *client* hook process persists that
  pairing (:mod:`yoke_contracts.cursor_session_map`) — a shell Cursor
  spawns later carries only its own conversation id, and only that side
  can see this machine's machine home.

Field names below are the measured wire shape of Cursor IDE 3.14.7 and
cursor-agent 2026.07.23; re-verify against newer builds (the vendor owns
the schema).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

from yoke_cli.config import machine_config
from yoke_contracts import cursor_session_map
from yoke_contracts.cursor_remount_expect import REMOUNT_REFUSAL_PAYLOAD_FIELD
from yoke_contracts.hook_runner.chain_registry import SESSION_START_EVENT
from yoke_contracts.payload_session_fold import (
    fold_conversation_session_id,
    fold_payload_session_id,
)


# Cursor tool vocabulary -> canonical chain matcher vocabulary. Only names
# that differ are listed; unknown names pass through to PreToolUse ``_default``.
_TOOL_NAME_CANONICAL: Dict[str, str] = {
    "Shell": "Bash",
    "StrReplace": "Edit",
}

# Events whose payload is a shell execution without a tool_name field.
_SHELL_EVENTS = {"beforeShellExecution", "afterShellExecution"}


def read_stdin() -> str:
    """Best-effort stdin read. Returns empty string on any failure."""
    try:
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def _parse_json(payload: str) -> Dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_payload(payload: str) -> Dict[str, Any]:
    """Parse Cursor hook stdin and canonicalize chain-facing fields.

    Returns the original payload dict with these normalizations applied:

    - ``tool_name`` mapped through the canonical vocabulary
      (``Shell`` -> ``Bash``).
    - Shell-execution events (`beforeShellExecution`/`afterShellExecution`)
      gain ``tool_name="Bash"`` and ``tool_input={"command": ...}`` so the
      Bash chain's matcher resolution and command lints read one shape.
      ``afterShellExecution`` output lands in ``tool_output``.
    - ``container_session_id`` is populated for every event (see
      :func:`resolve_container_session_id`); ``is_subagent_session`` flags
      payloads whose own ``session_id`` differs from the container.

    The original Cursor-native keys are preserved alongside the
    canonical ones — policies that want the raw shape still get it.
    """
    data = _parse_json(payload)
    if not data:
        return {}

    event = str(data.get("hook_event_name", ""))

    tool_name = data.get("tool_name")
    if isinstance(tool_name, str) and tool_name in _TOOL_NAME_CANONICAL:
        data["tool_name"] = _TOOL_NAME_CANONICAL[tool_name]

    if event in _SHELL_EVENTS and "tool_name" not in data:
        data["tool_name"] = "Bash"
        tool_input = data.get("tool_input")
        if not isinstance(tool_input, dict):
            tool_input = {}
        tool_input.setdefault("command", data.get("command", ""))
        data["tool_input"] = tool_input
        if event == "afterShellExecution" and "output" in data:
            data.setdefault("tool_output", data.get("output"))

    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("working_directory", "workdir"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                tool_input.setdefault("workdir", value)
                break

    from yoke_core.domain.session_ambient_identity import (
        is_conversation_shaped_session_id,
    )

    stamped = data.get("session_id")
    keep_stamped = (
        isinstance(stamped, str)
        and stamped.strip()
        and (data.get("identity_stamped") is True
             or not is_conversation_shaped_session_id(data, session_id=stamped))
    )
    container = resolve_container_session_id(data)
    if container:
        data["container_session_id"] = container
        session_id = str(data.get("session_id", ""))
        own_value = data.get("conversation_id")
        own = (
            own_value.strip()
            if isinstance(own_value, str) and own_value.strip()
            else session_id
        )
        if not session_id:
            data["session_id"] = container
            session_id = container
        if not own:
            own = session_id
        folded = bool(own) and own != container
        evidence = container_session_id_from_evidence(data) if folded else ""
        data["is_subagent_session"] = folded and bool(evidence) and own != evidence
        data["is_worktree_remap_session"] = folded and not data["is_subagent_session"]
        if data["is_subagent_session"]:
            # Container model: the top-level session owns all activity, so
            # every downstream consumer (telemetry, registration, policy)
            # reads the container id from ``session_id``; the subagent's
            # own id stays available for correlation.
            data["subagent_session_id"] = own
            if not keep_stamped:
                data["session_id"] = container
        elif data["is_worktree_remap_session"]:
            data["remapped_conversation_id"] = own
            if not keep_stamped:
                data["session_id"] = container
    else:
        refusal = data.get(REMOUNT_REFUSAL_PAYLOAD_FIELD)
        arriving = (
            refusal.get("arriving_conversation_id")
            if isinstance(refusal, dict)
            else None
        )
        if isinstance(arriving, str) and arriving:
            # The liveness gate deliberately keeps the arriving conversation
            # distinct so the ordinary foreign-lane guard can name the holder
            # and lane. This stamp is a refusal identity, never an alias.
            data["container_session_id"] = arriving
            data["identity_stamped"] = True
            data["session_id"] = arriving

    return data


def payload_field(payload: str, field: str) -> str:
    """Extract a top-level field from hook JSON as a string.

    Booleans stringify to ``"true"``/``"false"``; ``None`` becomes ``""``.
    """
    data = _parse_json(payload)
    value = data.get(field, "")
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def container_session_id_from_evidence(data: Dict[str, Any]) -> str:
    """Resolve the container session from evidence that names it directly.

    Delegates to :mod:`yoke_contracts.cursor_session_map`, which owns the
    rule because the client hook process applies it too — that side does
    the recording, being the only one that can see this machine's
    transcript env and machine home.
    """
    return cursor_session_map.container_session_id_from_evidence(data)


def _top_level_session_start_id(data: Dict[str, Any]) -> str:
    """Return the first top-level Cursor id before its map entry exists."""
    event = data.get("hook_event_name")
    session_id = data.get("session_id")
    conversation_id = data.get("conversation_id")
    if not all(
        isinstance(value, str)
        for value in (
            event,
            session_id,
            conversation_id,
        )
    ):
        return ""
    session_id = session_id.strip()
    conversation_id = conversation_id.strip()
    if (
        event.casefold() == SESSION_START_EVENT.casefold()
        and session_id
        and session_id == conversation_id
    ):
        return session_id
    return ""


def resolve_container_session_id(data: Dict[str, Any]) -> str:
    """Resolve the top-level (container) session id for a Cursor hook event.

    A client-stamped ``container_session_id`` wins, including an explicit
    empty value: the client owns the conversation map and empty beats a raw
    conversation. Every unstamped conversation-shaped channel uses that same
    map fold before it can become identity. A linked-worktree claim-holder is
    already a registered session and remains the non-conversation fallback.

    Yoke registers only the container session; sub-session and worktree-
    remapped conversation activity folds into it.
    """
    stamped = data.get("container_session_id")
    if isinstance(stamped, str):
        return stamped.strip()
    # Dispatch helpers also call this resolver on payloads that parsing has
    # already folded; their derived flags make session_id canonical identity.
    if (
        data.get("is_subagent_session") is True
        or data.get("is_worktree_remap_session") is True
    ):
        canonical = data.get("session_id")
        if isinstance(canonical, str):
            return canonical.strip()
    try:
        map_dir = (
            machine_config.yoke_home() / cursor_session_map.CURSOR_SESSION_MAP_DIR_NAME
        )
    except Exception:  # noqa: BLE001 — fold must never break payload parse
        map_dir = None
    resolved = container_session_id_from_evidence(data)
    if resolved:
        return (
            fold_conversation_session_id(resolved, map_dir)
            if map_dir is not None
            else ""
        )
    try:
        from yoke_core.hooks.cursor_worktree_session_fold import (
            resolve_worktree_remap_container,
        )

        holder = resolve_worktree_remap_container(data)
    except Exception:  # noqa: BLE001 — fold must never break payload parse
        holder = ""
    if holder:
        return holder
    folded = fold_payload_session_id(data, map_dir) if map_dir is not None else None
    if folded is not None:
        return folded or _top_level_session_start_id(data)
    return (
        fold_conversation_session_id(data.get("conversation_id"), map_dir)
        if map_dir is not None
        else ""
    )


def resolve_session_id(payload: str) -> str:
    """Resolve the Yoke session identity for a Cursor hook invocation.

    Resolution order:

    1. ``YOKE_SESSION_ID`` — explicit pin, wins everywhere.
    2. The container session id (top-level session), because Yoke's
       container model attributes all activity — main and subagent — to
       the top-level session.

    Returns empty string when no source has a value.
    """
    pinned = os.environ.get("YOKE_SESSION_ID", "")
    if pinned:
        return pinned
    return resolve_container_session_id(_parse_json(payload))


def is_folded_cursor_session(payload: Dict[str, Any]) -> bool:
    """True when the payload's own conversation folds onto a container."""
    return (
        payload.get("is_subagent_session") is True
        or payload.get("is_worktree_remap_session") is True
    )


def resolve_root(payload: str = "") -> str:
    """Resolve the workspace the Cursor harness opened at.

    Resolution order (harness-workspace semantics, payload-first):

    1. Payload ``workspace_roots[0]`` — the workspace Cursor opened.
    2. Payload ``cwd`` — present on tool events.
    3. ``CURSOR_PROJECT_DIR`` env — exported to every hook process.
    4. ``YOKE_ROOT`` env — explicit pin.

    Returns empty string when no source resolves; callers degrade
    gracefully rather than raising.
    """
    data = _parse_json(payload) if payload else {}
    roots = data.get("workspace_roots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str) and roots[0]:
        return roots[0]
    cwd = data.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    for env_var in ("CURSOR_PROJECT_DIR", "YOKE_ROOT"):
        value = os.environ.get(env_var, "")
        if value:
            return value
    return ""
