"""Client identity stamping for quiet remounts and live second windows."""

from __future__ import annotations

import json

from yoke_contracts.session_identity import AMBIENT_ENV_VARS
from yoke_contracts.cursor_remount_expect import (
    REMOUNT_REFUSAL_PAYLOAD_FIELD,
    write_remount_expect,
)
from yoke_contracts.cursor_session_map import (
    CURSOR_SESSION_MAP_DIR_NAME,
    recorded_session_id_for_conversation,
)
from yoke_harness.hooks.identity_stamp import record_then_stamp
from yoke_harness.hooks.relay_identity_guard import refuse_unstamped_relay


HOLDER = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REMAPPED = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _install_holder_lookup(monkeypatch) -> None:
    class _Resp:
        success = True
        result = {"holder": {"session_id": HOLDER}}

    import yoke_cli.commands._helpers as helpers
    import yoke_cli.transport.dispatcher as disp

    monkeypatch.setattr(helpers, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(helpers, "item_target", lambda *_a, **_k: {})
    monkeypatch.setattr(disp, "build_actor", lambda **_k: {})
    monkeypatch.setattr(disp, "call_dispatcher", lambda **_k: _Resp())


def _payload(tmp_path) -> dict:
    return {
        "session_id": REMAPPED,
        "conversation_id": REMAPPED,
        "workspace_roots": [str(tmp_path / "repo" / ".worktrees" / "YOK-9")],
        "tool_name": "Write",
    }


def _prepare(tmp_path, monkeypatch):
    home = tmp_path / "home"
    map_dir = home / CURSOR_SESSION_MAP_DIR_NAME
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    write_remount_expect(map_dir, HOLDER, HOLDER)
    _install_holder_lookup(monkeypatch)
    return map_dir, _payload(tmp_path)


def test_silent_remount_keeps_client_stamp_continuity(tmp_path, monkeypatch) -> None:
    map_dir, payload = _prepare(tmp_path, monkeypatch)
    started = json.loads(
        record_then_stamp(dict(payload), json.dumps(payload), "cursor", "SessionStart")
    )
    assert started["session_id"] == HOLDER
    assert recorded_session_id_for_conversation(map_dir, REMAPPED) is None

    stamped = json.loads(
        record_then_stamp(dict(payload), json.dumps(payload), "cursor", "PreToolUse")
    )
    assert stamped["session_id"] == HOLDER
    assert recorded_session_id_for_conversation(map_dir, REMAPPED) == HOLDER


def test_live_second_window_is_refused_with_holder_and_lane(
    tmp_path,
    monkeypatch,
) -> None:
    map_dir, payload = _prepare(tmp_path, monkeypatch)
    record_then_stamp(dict(payload), json.dumps(payload), "cursor", "SessionStart")
    write_remount_expect(map_dir, HOLDER, HOLDER)
    refused = json.loads(
        record_then_stamp(dict(payload), json.dumps(payload), "cursor", "PreToolUse")
    )
    assert refused["session_id"] == REMAPPED
    assert refused[REMOUNT_REFUSAL_PAYLOAD_FIELD]["holder_session_id"] == HOLDER
    message = refuse_unstamped_relay(refused)
    assert message is not None
    assert HOLDER in message
    assert "YOK-9" in message
