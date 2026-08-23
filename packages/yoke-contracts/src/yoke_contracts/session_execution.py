"""Normalize whether work is executing inside an in-process subagent.

Fleet messaging addresses registered top-level harness sessions.  Child
agents share or fold onto that identity for ownership and telemetry, so the
resolved session id alone cannot decide whether a Fleet operation belongs to
the parent.  This module owns the client-observable execution fact used by
hook delivery and message commands.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping, Optional, Union


SUBAGENT_EXECUTION_PAYLOAD_KEY = "subagent_execution"
_CURSOR_CONVERSATION_ENV = "CURSOR_CONVERSATION_ID"
_CURSOR_TRANSCRIPT_ENV = "CURSOR_TRANSCRIPT_PATH"


def _nonempty(value: object) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _cursor_transcript_is_child(path: str) -> bool:
    return "subagents" in Path(path.replace("\\", "/")).parts


def is_subagent_execution(
    payload: Optional[Mapping[str, Any]] = None,
    env: Optional[Mapping[str, str]] = None,
    *,
    cursor_projects_root: Optional[Union[str, "os.PathLike[str]"]] = None,
) -> bool:
    """Return a conservative, cross-harness child-execution fact.

    Claude supplies ``agent_type``/``YOKE_HOOK_AGENT_TYPE``. Codex exports
    the registered parent in ``CODEX_SESSION_ID`` and the running thread in
    ``CODEX_THREAD_ID``. Cursor hook normalization supplies
    ``is_subagent_session``; a child shell is recovered from its nested
    transcript layout when hook payload metadata is unavailable.

    Unknown evidence returns ``False`` so ordinary top-level sessions and
    independently launched workers remain Fleet participants.
    """
    data = payload or {}
    source = os.environ if env is None else env
    if data.get(SUBAGENT_EXECUTION_PAYLOAD_KEY) is True:
        return True
    if data.get("is_subagent_session") is True:
        return True
    if _nonempty(data.get("subagent_session_id")):
        return True
    if _nonempty(data.get("parent_conversation_id")):
        return True
    if _nonempty(data.get("agent_type")):
        return True
    if _nonempty(source.get("YOKE_HOOK_AGENT_TYPE")):
        return True

    codex_parent = _nonempty(source.get("CODEX_SESSION_ID"))
    codex_thread = _nonempty(source.get("CODEX_THREAD_ID"))
    if codex_parent and codex_thread and codex_parent != codex_thread:
        return True

    conversation = _nonempty(source.get(_CURSOR_CONVERSATION_ENV))
    transcript = _nonempty(source.get(_CURSOR_TRANSCRIPT_ENV))
    if conversation and transcript and _cursor_transcript_is_child(transcript):
        return True
    if conversation:
        try:
            from yoke_contracts.cursor_session_map import (
                resolve_container_from_subagent_transcript_layout,
            )

            return bool(
                resolve_container_from_subagent_transcript_layout(
                    conversation,
                    projects_root=cursor_projects_root,
                )
            )
        except Exception:
            return False
    return False


__all__ = ["SUBAGENT_EXECUTION_PAYLOAD_KEY", "is_subagent_execution"]
