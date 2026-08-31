"""Harness-native identity carried by relayed and local registration."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

from yoke_cli.config import machine_config
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_core.hooks import session_lifecycle_client
from yoke_harness.hooks.identity_relay import (
    client_native_thread_id,
    relay_identity_payload,
)
from yoke_contracts.session_model_facts import SessionModelFacts


def test_captures_codex_thread_id_for_codex_executor():
    with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-42"}, clear=True):
        assert client_native_thread_id("codex-desktop") == "thread-42"


def test_ignores_codex_env_for_claude_executor():
    with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-42"}, clear=True):
        assert client_native_thread_id("claude-code") is None


def test_none_when_unset():
    with mock.patch.dict(os.environ, {}, clear=True):
        assert client_native_thread_id("codex-cli") is None


def test_relay_identity_payload_carries_native_thread_id():
    with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-42"}, clear=True):
        payload = relay_identity_payload(
            "SessionStart", {"session_id": "s1"}, "codex-desktop"
        )

    assert payload["native_thread_id"] == "thread-42"


def test_cursor_uses_the_hook_written_conversation_map(
    monkeypatch, tmp_path: Path
) -> None:
    map_dir = tmp_path / CURSOR_SESSION_MAP_DIR_NAME
    record_conversation_session("cursor-conversation", "yoke-session", map_dir)
    monkeypatch.setattr(machine_config, "yoke_home", lambda: tmp_path)
    monkeypatch.setenv("CURSOR_CONVERSATION_ID", "cursor-conversation")
    monkeypatch.setenv("YOKE_SESSION_ID", "yoke-session")

    assert client_native_thread_id("cursor-desktop", "yoke-session") == (
        "cursor-conversation"
    )
    assert client_native_thread_id("cursor-desktop", "other-session") is None
    relayed = relay_identity_payload(
        "SessionStart", {"session_id": "yoke-session"}, "cursor-desktop"
    )
    assert relayed["native_thread_id"] == "cursor-conversation"


def test_claude_uses_a_distinct_native_session(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "yoke-session")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-session")

    assert client_native_thread_id("claude-code", "yoke-session") == ("claude-session")
    assert client_native_thread_id("claude-code", "claude-session") is None
    relayed = relay_identity_payload(
        "SessionStart", {"session_id": "yoke-session"}, "claude-code"
    )
    assert relayed["native_thread_id"] == "claude-session"


def test_local_registration_resolves_native_identity(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        session_lifecycle_client, "_relay_owns_registration", lambda: False
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_local_authority_active", lambda: False
    )
    monkeypatch.setattr(
        session_lifecycle_client, "_project_id_for_root", lambda _root: 1
    )
    monkeypatch.setattr(
        "yoke_core.hooks.helpers_identity.detect_native_thread_id",
        lambda executor, session_id: f"native:{executor}:{session_id}",
    )
    monkeypatch.setattr(
        session_lifecycle_client.service_client,
        "register_session",
        lambda *args: calls.append(args),
    )

    result = session_lifecycle_client.register_harness_session(
        root="/repo",
        session_id="yoke-session",
        executor="cursor",
        provider="cursor",
        model_facts=SessionModelFacts(requested_model="composer"),
    )

    assert result == ""
    assert calls[0][-1] == "native:cursor:yoke-session"
