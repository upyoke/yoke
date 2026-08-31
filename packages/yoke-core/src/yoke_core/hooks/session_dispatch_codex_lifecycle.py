"""Codex adapters for the harness-neutral lifecycle client."""

from __future__ import annotations

from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.hooks import session_lifecycle_client
from yoke_core.hooks.helpers_identity import detect_native_thread_id


def recovery_command(
    session_id: str,
    root: str,
    requested_model: str,
    entrypoint: Optional[str],
) -> str:
    return session_lifecycle_client.session_begin_recovery_command(
        root=root,
        session_id=session_id,
        executor="codex",
        provider="openai",
        requested_model=requested_model,
        entrypoint=entrypoint,
    )


def register(
    root: str,
    session_id: str,
    model_facts: SessionModelFacts,
    entrypoint: Optional[str],
) -> str:
    return session_lifecycle_client.register_harness_session(
        root=root,
        session_id=session_id,
        executor="codex",
        provider="openai",
        model_facts=model_facts,
        entrypoint=entrypoint,
        native_thread_id=detect_native_thread_id(),
    )


def touch(root: str, session_id: str) -> int:
    return session_lifecycle_client.touch_harness_session(root, session_id)
