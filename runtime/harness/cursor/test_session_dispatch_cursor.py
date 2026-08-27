"""Cursor session-lifecycle dispatch: orientation channel and side effects.

The sessionStart reply must be Cursor's JSON shape with the orientation
under ``additional_context``; prompt-submit performs side effects only.
Registration goes through the cursor lifecycle adapter with
executor=cursor / provider=cursor and the payload-named model.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.hooks import session_dispatch_cursor as dispatch_cursor
from yoke_core.hooks.types import HookContext

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

    monkeypatch.setattr(dispatch_cursor._lifecycle, "register", fake_register)
    monkeypatch.setattr(dispatch_cursor._lifecycle, "touch", fake_touch)
    monkeypatch.setattr(dispatch_cursor, "_render_resume_block", lambda *a, **k: "")
    monkeypatch.setattr(
        dispatch_cursor,
        "_render_orientation",
        lambda record, root, err: f"orientation for {record.payload['session_id']}\n",
    )
    monkeypatch.delenv("CURSOR_INVOKED_AS", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    return calls


def test_cursor_dispatch_consumes_the_shared_orientation_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"session_id": MAIN}
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.render_orientation",
        lambda received, root: f"shared {received['session_id']} at {root}\n",
    )

    body = dispatch_cursor._render_orientation(
        _context(payload),
        "/repo",
        "",
    )

    assert body == f"shared {MAIN} at /repo\n"


def test_cursor_dispatch_does_not_duplicate_client_orientation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain.session_orientation import (
        CLIENT_ORIENTATION_PRESENT_KEY,
    )

    payload = {
        "session_id": MAIN,
        CLIENT_ORIENTATION_PRESENT_KEY: True,
    }
    monkeypatch.setattr(
        "yoke_core.domain.session_orientation.render_orientation",
        lambda *_a, **_k: pytest.fail("client already supplied orientation"),
    )

    assert (
        dispatch_cursor._render_orientation(
            _context(payload),
            "/repo",
            "",
        )
        == ""
    )


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


def test_prompt_submit_is_silent_and_does_not_heartbeat(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.hooks.session_dispatch._first_prompt",
        lambda session_id, codex: False,
    )
    payload = {"session_id": MAIN, "model": "composer-2.5"}
    out = dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert out == ""
    assert quiet_side_effects["touch"] == []
    assert quiet_side_effects["register"] == []


def test_later_prompt_does_not_register_when_touch_would_have_failed(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dispatch_cursor._lifecycle, "touch", lambda root, sid: 1)
    monkeypatch.setattr(
        "yoke_core.hooks.session_dispatch._first_prompt",
        lambda session_id, codex: False,
    )
    payload = {"session_id": MAIN, "model": "composer-2.5"}
    dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert quiet_side_effects["register"] == []
    assert quiet_side_effects["touch"] == []


def test_prompt_submit_heals_a_session_that_opened_without_a_model(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A surface that named no model when the session opened gets one free
    correction on its first prompt; registration is upgrade-only and
    later prompts do not heartbeat."""
    monkeypatch.setattr(
        "yoke_core.hooks.session_dispatch._first_prompt",
        lambda session_id, codex: True,
    )
    payload = {"session_id": MAIN, "model": "composer-2.5"}
    dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert quiet_side_effects["touch"] == []
    assert quiet_side_effects["register"] == [
        ("/repo", MAIN, "composer-2.5", "cursor-desktop")
    ]


def test_prompt_submit_does_not_heal_without_a_named_model(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yoke_core.hooks.session_dispatch._first_prompt",
        lambda session_id, codex: True,
    )
    payload = {"session_id": MAIN, "model": "default"}
    dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert quiet_side_effects["register"] == []


def test_session_start_registers_the_display_model_when_it_is_the_only_one(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The terminal agent opens a session naming ``model`` and no
    ``model_id``. That is a real answer, not a placeholder, and it is the
    only one the session gets - no mid-stream event reports another."""
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    payload = {"session_id": MAIN, "model": "cursor-grok-4.6-high-fast"}
    dispatch_cursor.run_session_start(_context(payload), "/repo")
    assert quiet_side_effects["register"] == [
        ("/repo", MAIN, "cursor-grok-4.6-high-fast", "cursor-cli")
    ]


def test_session_start_refuses_to_store_the_default_placeholder(
    quiet_side_effects: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The terminal agent names ``"default"`` — its word for "whatever the
    user configured" — on every session-opening event. Storing that string
    as a model would misreport the session and, because it is not a
    recognized placeholder downstream, block the later upgrade."""
    monkeypatch.setenv("CURSOR_INVOKED_AS", "cursor-agent")
    payload = {"session_id": MAIN, "model": "default"}
    dispatch_cursor.run_session_start(_context(payload), "/repo")
    assert quiet_side_effects["register"] == [("/repo", MAIN, "unknown", "cursor-cli")]


def test_session_start_skips_register_for_subagent_session(
    quiet_side_effects: dict,
) -> None:
    payload = {
        "session_id": MAIN,
        "conversation_id": MAIN,
        "is_subagent_session": True,
        "subagent_session_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "model_id": "composer-2.5",
    }
    out = dispatch_cursor.run_session_start(_context(payload), "/repo")
    assert json.loads(out) == {"additional_context": ""}
    assert quiet_side_effects["register"] == []


def test_prompt_submit_skips_touch_for_subagent_session(
    quiet_side_effects: dict,
) -> None:
    payload = {
        "session_id": MAIN,
        "is_subagent_session": True,
        "model": "composer-2.5",
    }
    out = dispatch_cursor.run_prompt_submit(_context(payload), "/repo")
    assert out == ""
    assert quiet_side_effects["touch"] == []
    assert quiet_side_effects["register"] == []
