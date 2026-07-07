"""Codex adapters for the harness-neutral lifecycle client."""

from __future__ import annotations

from typing import Optional

from runtime.harness.hook_runner import session_lifecycle_client


def recovery_command(
    session_id: str,
    root: str,
    model: str,
    entrypoint: Optional[str],
) -> str:
    return session_lifecycle_client.session_begin_recovery_command(
        root=root,
        session_id=session_id,
        executor="codex",
        provider="openai",
        model=model,
        entrypoint=entrypoint,
    )


def register(
    root: str,
    session_id: str,
    model: str,
    entrypoint: Optional[str],
) -> str:
    return session_lifecycle_client.register_harness_session(
        root=root,
        session_id=session_id,
        executor="codex",
        provider="openai",
        model=model,
        entrypoint=entrypoint,
    )


def touch(root: str, session_id: str) -> int:
    return session_lifecycle_client.touch_harness_session(root, session_id)
