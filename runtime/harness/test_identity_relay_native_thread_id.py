"""``client_native_thread_id`` — the wire-carried Codex thread mapping.

Companion to ``test_hook_helpers_identity.py`` (the local-detection twin,
``detect_native_thread_id``). This is the client-side probe that puts the
same value on the wire for a relayed (https) registration, where the
server-side registrar has no local environment of its own to read.
"""

from __future__ import annotations

import os
from unittest import mock

from yoke_harness.hooks.identity_relay import (
    client_native_thread_id,
    relay_identity_payload,
)


def test_captures_codex_thread_id_for_codex_executor():
    with mock.patch.dict(os.environ, {"CODEX_THREAD_ID": "thread-42"}, clear=True):
        assert client_native_thread_id("codex-desktop") == "thread-42"


def test_none_for_non_codex_executor_even_when_env_leaks():
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
