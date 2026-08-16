"""Hook-runner and client-relay stamp payload.session_id from ambient identity."""

from __future__ import annotations

import json

from runtime.harness.claude.adapter import CAPABILITY as CLAUDE_CAPABILITY
from runtime.harness.hook_runner import runner as runner_module
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_harness.hooks.identity_stamp import stamp_hook_stdin


def test_local_context_stamps_env_session_id(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-stamped")
    payload = {"tool_name": "Bash"}
    context = runner_module._build_context(
        event_name="PreToolUse",
        capability=CLAUDE_CAPABILITY,
        payload=payload,
        remote=False,
    )
    assert context.session_id == "sid-stamped"
    assert payload["session_id"] == "sid-stamped"


def test_remote_context_does_not_adopt_server_env(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-server")
    payload = {"tool_name": "Bash"}
    context = runner_module._build_context(
        event_name="PreToolUse",
        capability=CLAUDE_CAPABILITY,
        payload=payload,
        remote=True,
    )
    assert context.session_id is None
    assert "session_id" not in payload


def test_stamp_fills_empty_payload_from_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-env")
    payload: dict = {"tool_name": "Bash"}
    stdin = stamp_hook_stdin("{}", payload)
    assert payload["session_id"] == "sid-env"
    assert json.loads(stdin)["session_id"] == "sid-env"


def test_stamp_preserves_existing_session_id(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-env")
    payload = {"session_id": "sid-payload"}
    original = json.dumps(payload)
    assert stamp_hook_stdin(original, payload) == original


def test_stamp_fills_from_cursor_session_map(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
        monkeypatch.delenv(name, raising=False)
    conversation = "conv-1"
    record_conversation_session(
        conversation, "sid-mapped", home / CURSOR_SESSION_MAP_DIR_NAME,
    )
    monkeypatch.setenv(CURSOR_CONVERSATION_ENV_VAR, conversation)
    payload: dict = {"tool_name": "Write"}
    stamp_hook_stdin("{}", payload)
    assert payload["session_id"] == "sid-mapped"
