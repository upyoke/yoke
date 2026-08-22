"""Hook-runner and client-relay stamp payload.session_id from ambient identity."""

from __future__ import annotations

import json

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_core.hooks.claude_adapter import CAPABILITY as CLAUDE_CAPABILITY
from yoke_core.hooks import runner as runner_module
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    record_conversation_session,
)
from yoke_harness.hooks.identity_stamp import record_then_stamp, stamp_hook_stdin


def _transcript(conversation_id: str) -> str:
    return (
        "/home/u/.cursor/projects/p/agent-transcripts/"
        f"{conversation_id}/{conversation_id}.jsonl"
    )


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


def test_stamp_preserves_claude_and_codex_session_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-env")
    for executor, session_id in (
        ("claude-code", "claude-session"),
        ("codex", "codex-thread"),
    ):
        payload = {
            "session_id": session_id,
            "transcript_path": _transcript(session_id),
        }
        original = json.dumps(payload)
        stamped = json.loads(record_then_stamp(
            payload, original, executor, "PreToolUse",
        ))
        assert stamped["session_id"] == session_id
        assert stamped["identity_stamped"] is True


def test_cursor_payload_without_transcript_is_unchanged(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    payload = {"session_id": "cursor-session", "tool_name": "Write"}
    original = json.dumps(payload)
    stamped = json.loads(record_then_stamp(
        payload, original, "cursor", "PreToolUse",
    ))
    assert stamped["session_id"] == "cursor-session"
    assert stamped["identity_stamped"] is True


def test_stamp_folds_mapped_conversation_id(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    conversation = "conv-remount"
    record_conversation_session(
        conversation, "sid-holder", home / CURSOR_SESSION_MAP_DIR_NAME,
    )
    payload = {
        "session_id": conversation,
        "conversation_id": conversation,
        "tool_name": "Write",
    }
    stdin = stamp_hook_stdin(json.dumps(payload), payload)
    assert payload["session_id"] == "sid-holder"
    assert json.loads(stdin)["session_id"] == "sid-holder"


def test_stamp_clears_unmapped_conversation(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("YOKE_SESSION_ID", "sid-other")
    conversation = "conv-unknown"
    payload = {"session_id": conversation, "conversation_id": conversation}
    original = json.dumps(payload)
    stdin = stamp_hook_stdin(original, payload)
    assert json.loads(stdin)["session_id"] == ""
    assert payload["session_id"] == ""


def test_stamp_folds_transcript_container_identity(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    conversation = "conv-transcript-remount"
    record_conversation_session(
        conversation, "sid-holder", home / CURSOR_SESSION_MAP_DIR_NAME,
    )
    payload = {
        "session_id": conversation,
        "conversation_id": conversation,
        "transcript_path": _transcript(conversation),
        "tool_name": "Write",
    }
    stamped = json.loads(record_then_stamp(
        payload, json.dumps(payload), "cursor", "PreToolUse",
    ))
    assert stamped["session_id"] == "sid-holder"
    assert stamped["container_session_id"] == "sid-holder"


def test_record_then_stamp_establishes_unmapped_transcript_container(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    conversation = "conv-transcript-unknown"
    payload = {
        "session_id": conversation,
        "conversation_id": conversation,
        "transcript_path": _transcript(conversation),
        "tool_name": "Write",
    }
    stamped = json.loads(record_then_stamp(
        payload, json.dumps(payload), "cursor", "PreToolUse",
    ))
    assert stamped["session_id"] == conversation
    assert stamped["container_session_id"] == conversation


def test_record_then_stamp_writes_remount_expect_on_main(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    conversation = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    payload = {
        "session_id": conversation,
        "conversation_id": conversation,
        "workspace_roots": [str(tmp_path / "repo")],
        "tool_name": "Write",
    }
    stamped = json.loads(record_then_stamp(
        payload, json.dumps(payload), "cursor", "PreToolUse",
    ))
    assert stamped["session_id"] == conversation
    from yoke_contracts.cursor_remount_expect import remount_expect_is_live

    assert remount_expect_is_live(
        home / CURSOR_SESSION_MAP_DIR_NAME, conversation,
    )


def test_record_then_stamp_skips_self_map_on_worktree_lane(
    tmp_path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    conversation = "conv-remount-absent"
    payload = {
        "session_id": conversation,
        "conversation_id": conversation,
        "workspace_roots": [str(tmp_path / "repo" / ".worktrees" / "YOK-9")],
        "tool_name": "Write",
    }
    stamped = json.loads(record_then_stamp(
        payload, json.dumps(payload), "cursor", "PreToolUse",
    ))
    assert stamped["session_id"] == ""
    from yoke_contracts.cursor_session_map import recorded_session_id_for_conversation

    assert not recorded_session_id_for_conversation(
        home / CURSOR_SESSION_MAP_DIR_NAME, conversation,
    )


def test_stamp_fills_from_cursor_session_map(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    conversation = "conv-1"
    record_conversation_session(
        conversation, "sid-mapped", home / CURSOR_SESSION_MAP_DIR_NAME,
    )
    monkeypatch.setenv(CURSOR_CONVERSATION_ENV_VAR, conversation)
    payload: dict = {"tool_name": "Write"}
    stamp_hook_stdin("{}", payload)
    assert payload["session_id"] == "sid-mapped"
