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
  write should attribute to.

Field names below are the measured wire shape of Cursor IDE 3.14.7 and
cursor-agent 2026.07.23; re-verify against newer builds (the vendor owns
the schema).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import PurePosixPath
from typing import Any, Dict


# Cursor tool vocabulary -> canonical chain matcher vocabulary. Only names
# that differ are listed; unknown names pass through untouched so new
# Cursor tools degrade to "no registered chain" rather than crashing.
_TOOL_NAME_CANONICAL: Dict[str, str] = {
    "Shell": "Bash",
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

    container = resolve_container_session_id(data)
    if container:
        data["container_session_id"] = container
        own = str(data.get("session_id", ""))
        data["is_subagent_session"] = bool(own) and own != container

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


def _transcript_session_id(transcript_path: str) -> str:
    """Return the session id encoded in a Cursor transcript path.

    Cursor transcript files live at
    ``.../agent-transcripts/<session-id>/<session-id>.jsonl``; the stem is
    the session id. Empty input returns empty output.
    """
    if not transcript_path:
        return ""
    return PurePosixPath(transcript_path).stem


def resolve_container_session_id(data: Dict[str, Any]) -> str:
    """Resolve the top-level (container) session id for a Cursor hook event.

    Resolution order:

    1. ``CURSOR_TRANSCRIPT_PATH`` env — points at the **top-level** session
       transcript in every hook process, including hooks fired for subagent
       activity. Unset for roughly the first events of a fresh session, so
       the payload fallbacks below stay load-bearing.
    2. ``parent_conversation_id`` payload field — present on subagent
       lifecycle events; names the parent directly.
    3. The payload's own ``transcript_path`` — equals the session's own
       transcript; for a top-level event that IS the container.
    4. The payload's own ``session_id`` / ``conversation_id`` — correct for
       top-level events; for a subagent event with none of the above
       signals this attributes to the sub-session (callers holding earlier
       ``subagentStart`` state can correct it).

    Yoke registers only the container session; sub-session activity folds
    into it.
    """
    env_transcript = os.environ.get("CURSOR_TRANSCRIPT_PATH", "")
    resolved = _transcript_session_id(env_transcript)
    if resolved:
        return resolved
    parent = data.get("parent_conversation_id")
    if isinstance(parent, str) and parent:
        return parent
    resolved = _transcript_session_id(str(data.get("transcript_path", "") or ""))
    if resolved:
        return resolved
    for key in ("session_id", "conversation_id"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


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
