"""Hook context construction shared by runner dispatch."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks.target import resolve_context_target_root
from yoke_core.hooks.types import HookContext


def _str_or(value: Any, default: Optional[str] = None) -> Optional[str]:
    return value if isinstance(value, str) else default


def build_context(
    *,
    event_name: str,
    capability: AdapterCapability,
    payload: dict[str, Any],
    remote: bool = False,
) -> HookContext:
    """Build a local or remote context from the executor payload."""
    tool_input = payload.get("tool_input")
    command_body = (
        _str_or(tool_input.get("command")) if isinstance(tool_input, dict) else None
    )
    session_id = _str_or(payload.get("session_id"))
    if not session_id and not remote:
        from yoke_core.domain.session_ambient_identity import (
            session_id_from_hook_payload,
        )

        session_id = session_id_from_hook_payload(payload) or None
        if session_id:
            payload["session_id"] = session_id
    payload_cwd = _str_or(payload.get("cwd"))
    cwd = payload_cwd if remote else (payload_cwd or os.getcwd())
    return HookContext(
        event_name=event_name,
        executor_family=capability.family,
        executor_surface=os.environ.get("YOKE_EXECUTOR", capability.family),
        payload=payload,
        tool_name=_str_or(payload.get("tool_name")),
        command_body=command_body,
        cwd=cwd,
        target_root=resolve_context_target_root(payload, payload_cwd),
        session_id=session_id,
        item_id=None,
        now=datetime.now(timezone.utc),
        remote=remote,
    )


__all__ = ["build_context"]
