"""Only Cursor hook events write ~/.yoke/cursor-session-map entries."""

from __future__ import annotations

import json

import pytest

from yoke_contracts.cursor_remount_expect import remount_expect_is_live
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    recorded_session_id_for_conversation,
)
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_harness.hooks.identity_stamp import record_then_stamp


CONVERSATION = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _prepare(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    payload = {
        "session_id": CONVERSATION,
        "conversation_id": CONVERSATION,
        "workspace_roots": [str(tmp_path / "repo")],
        "cwd": str(tmp_path / "repo"),
        "tool_name": "Shell",
    }
    return home / CURSOR_SESSION_MAP_DIR_NAME, payload


@pytest.mark.parametrize("executor", ["codex", "claude-code", "claude"])
@pytest.mark.parametrize("event_name", ["SessionStart", "PreToolUse"])
def test_non_cursor_hook_writes_no_session_map_files(
    tmp_path, monkeypatch, executor, event_name
) -> None:
    map_dir, payload = _prepare(tmp_path, monkeypatch)
    record_then_stamp(dict(payload), json.dumps(payload), executor, event_name)
    assert not map_dir.exists() or not any(map_dir.iterdir())


def test_cursor_hook_still_records_conversation_and_remount_expect(
    tmp_path, monkeypatch
) -> None:
    map_dir, payload = _prepare(tmp_path, monkeypatch)
    record_then_stamp(dict(payload), json.dumps(payload), "cursor", "PreToolUse")
    assert recorded_session_id_for_conversation(map_dir, CONVERSATION) == CONVERSATION
    assert remount_expect_is_live(map_dir, CONVERSATION)
