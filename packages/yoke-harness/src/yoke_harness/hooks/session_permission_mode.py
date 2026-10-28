"""Keep only the parent Claude session's latest hook-reported permission mode."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from uuid import UUID

from yoke_cli.config import machine_config
from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.refusal_recovery import compose_refusal


def _cache_path(session_id: str) -> Path:
    if str(UUID(session_id)) != session_id:
        raise ValueError("session identity is not a canonical UUID")
    return machine_config.cache_dir() / f"claude-permission-mode-{session_id}.json"


def capture_permission_mode(payload: dict, executor: str) -> None:
    """Record no prompt, tool input or subagent mode from the hook payload."""
    if (
        canonical_harness_id(executor) != "claude-code"
        or "agent_id" in payload
        or "permission_mode" not in payload
    ):
        return
    try:
        path = _cache_path(payload.get("session_id", ""))
    except (ValueError, TypeError, AttributeError):
        return
    staged = path.with_name(f"{path.name}.{os.getpid()}.staged")
    mode = payload["permission_mode"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text(
            json.dumps(
                {
                    "permission_mode": mode if isinstance(mode, str) else None,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(staged, path)
    except OSError:
        for target in (staged, path):
            try:
                target.unlink(missing_ok=True)
            except OSError:
                pass
        sys.stderr.write(
            compose_refusal(
                "HARNESS_POSTURE_UNVERIFIED: could not record this session's permission mode",
                recovery="restore write access to the Yoke cache, send any prompt in this chat, then rerun `yoke doctor run --session`",
            )
            + "\n"
        )


def read_permission_mode(session_id: str) -> dict | None:
    """Unreadable or absent records cannot establish the session's mode."""
    try:
        data = json.loads(_cache_path(session_id).read_text(encoding="utf-8"))
        if isinstance(data, dict) and "permission_mode" in data:
            return data
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None
