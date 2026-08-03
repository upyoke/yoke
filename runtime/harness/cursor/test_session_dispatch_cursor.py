"""Cursor session-lifecycle dispatch: orientation channel and side effects.

The sessionStart reply must be Cursor's JSON shape with the orientation
under ``additional_context``; prompt-submit performs side effects only.
Registration goes through the cursor lifecycle adapter with
executor=cursor / provider=cursor and the payload-named model.
"""

from __future__ import annotations

import json

import pytest

from runtime.harness.hook_runner import session_dispatch_cursor as dispatch_cursor
from runtime.harness.hook_runner.types import HookContext

MAIN = "11111111-2222-3333-4444-555555555555"


def _context(payload: dict) -> HookContext:
    return HookContext(
        event_name="SessionStart",
        executor_family="cursor",
        executor_surface="cursor-cli",
        payload=payload,
    )


@pytest.fixture
def quiet_side_effects(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"register": [], "touch": []}

    def fake_register(root, session_id, model, entrypoint):
        calls["register"].append((root, session_id, model, entrypoint))
        return ""

    def fake_touch(root, session_id):
        calls["touch"].append((root, session_id))
        return 0

    monkeypatch.setattr(
        dispatch_cursor._lifecycle, "register", fake_register
    )
    monkeypatch.setattr(dispatch_cursor._lifecycle, "touch", fake_touch)
    monkeypatch.setattr(
        dispatch_cursor, "export_bound_workspace_for_session", lambda *a, **k: None
    )
    monkeypatch.setattr(
        dispatch_cursor, "_render_resume_block", lambda *a, **k: ""
    )
    monkeypatch.setattr(
        dispatch_cursor,
        "_render_orientation",
        lambda session_id, root, err: f"orientation for {session_id}\n",
    )
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    return calls


def test_session_start_wraps_orientation_in_additional_context(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "hook_event_name": "sessionStart",
        "session_id": MAIN,
        "conversation_id": MAIN,
        "model": "composer-2.5-fast",
        "model_id": "composer-2.5",
    }
    out = dispatch_cursor.run_session_start(_context(payload), "/repo")
    envelope = json.loads(out)
    assert set(envelope) == {"additional_context"}
    assert f"orientation for {MAIN}" in envelope["additional_context"]


def test_session_start_registers_with_payload_model(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    payload = {"session_id": MAIN, "model_id": "composer-2.5", "model": "x"}
    dispatch_cursor.run_session_start(_context(payload), "/repo")
    assert quiet_side_effects["register"] == [
        ("/repo", MAIN, "composer-2.5", "cursor-cli")
    ]


def test_session_start_degrades_without_session_id(
    quiet_side_effects: dict,
) -> None:
    out = dispatch_cursor.run_session_start(_context({}), "/repo")
    envelope = json.loads(out)
    assert "degraded mode" in envelope["additional_context"]
    assert quiet_side_effects["register"] == []


def test_prompt_submit_is_silent_and_touches(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "runtime.harness.hook_runner.session_dispatch._first_prompt",
        lambda session_id, codex: False,
    )
    payload = {"session_id": MAIN, "model": "composer-2.5"}
    out = dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert out == ""
    assert quiet_side_effects["touch"] == [("/repo", MAIN)]
    assert quiet_side_effects["register"] == []


def test_prompt_submit_reregisters_when_touch_fails(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        dispatch_cursor._lifecycle, "touch", lambda root, sid: 1
    )
    monkeypatch.setattr(
        "runtime.harness.hook_runner.session_dispatch._first_prompt",
        lambda session_id, codex: False,
    )
    payload = {"session_id": MAIN, "model": "composer-2.5"}
    dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert quiet_side_effects["register"] == [
        ("/repo", MAIN, "composer-2.5", "cursor-desktop")
    ]
