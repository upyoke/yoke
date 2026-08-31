"""Cursor adapters for the harness-neutral lifecycle client.

Provider is ``cursor`` (the harness multiplexes model vendors within one
session; the active model is named per hook payload), and the model value
comes from the payload at each call site rather than an ambient probe.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.session_model_facts import SessionModelFacts

from yoke_core.hooks import session_lifecycle_client


def recovery_command(
    session_id: str,
    root: str,
    requested_model: str,
    entrypoint: Optional[str],
) -> str:
    return session_lifecycle_client.session_begin_recovery_command(
        root=root,
        session_id=session_id,
        executor="cursor",
        provider="cursor",
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
        executor="cursor",
        provider="cursor",
        model_facts=model_facts,
        entrypoint=entrypoint,
    )


def touch(root: str, session_id: str) -> int:
    return session_lifecycle_client.touch_harness_session(root, session_id)
