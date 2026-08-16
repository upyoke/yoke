"""Relay identity refusal, replay skip, and fold choke-point."""

from __future__ import annotations

import inspect

from yoke_core.domain.session_ambient_identity import (
    fold_raw_identity,
    is_hook_replay,
    resolve_env_session_id,
    session_id_from_hook_payload,
)
from yoke_harness.hooks.relay_identity_guard import (
    RELAY_REFUSAL_CONVERSATION,
    RELAY_REFUSAL_UNSTAMPED,
    refuse_unstamped_relay,
)


def test_refuse_unstamped_and_conversation_shaped() -> None:
    assert refuse_unstamped_relay({}) == RELAY_REFUSAL_UNSTAMPED
    payload = {
        "session_id": "conv-1",
        "conversation_id": "conv-1",
    }
    assert refuse_unstamped_relay(payload) == RELAY_REFUSAL_CONVERSATION


def test_refuse_trusts_identity_stamped() -> None:
    payload = {
        "session_id": "conv-1",
        "conversation_id": "conv-1",
        "identity_stamped": True,
    }
    assert refuse_unstamped_relay(payload) is None


def test_session_id_from_hook_payload_trusts_stamp() -> None:
    payload = {
        "session_id": "same-id",
        "conversation_id": "same-id",
        "identity_stamped": True,
    }
    assert session_id_from_hook_payload(payload, env={}) == "same-id"


def test_is_hook_replay_reads_env() -> None:
    assert is_hook_replay({"YOKE_HOOK_REPLAY": "1"}) is True
    assert is_hook_replay({}) is False


def test_identity_channels_call_fold_raw_identity() -> None:
    source = inspect.getsource(resolve_env_session_id)
    assert "fold_raw_identity" in source
    source = inspect.getsource(session_id_from_hook_payload)
    assert "fold_raw_identity" in source
    assert callable(fold_raw_identity)
