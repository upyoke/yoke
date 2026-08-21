"""Harness-shaped merging for client-composed startup context."""

from __future__ import annotations

import json

from yoke_core.domain.session_orientation import (
    CLIENT_ORIENTATION_PRESENT_KEY,
)
from yoke_core.hooks import local_entry
from yoke_harness.hooks.decision_render import (
    HOOK_SPECIFIC_OUTPUT_KEY,
    merge_allow_stdout,
    render_context_stdout,
)


def test_default_context_uses_claude_codex_envelope() -> None:
    stdout = render_context_stdout("orientation", "UserPromptSubmit")

    assert json.loads(stdout) == {
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "orientation",
        }
    }


def test_cursor_context_uses_session_start_envelope() -> None:
    stdout = render_context_stdout(
        "orientation",
        "SessionStart",
        cursor=True,
    )

    assert json.loads(stdout) == {"additional_context": "orientation"}


def test_cursor_context_joins_existing_session_start_body() -> None:
    first = json.dumps({"additional_context": "orientation"})
    second = json.dumps({"additional_context": "resume block"})

    merged = merge_allow_stdout(
        first,
        second,
        "SessionStart",
        cursor=True,
    )

    assert json.loads(merged) == {
        "additional_context": "orientation\n\nresume block",
    }


def test_cursor_context_replaces_empty_existing_body() -> None:
    orientation = json.dumps({"additional_context": "orientation"})
    empty = json.dumps({"additional_context": ""})

    merged = merge_allow_stdout(
        orientation,
        empty,
        "SessionStart",
        cursor=True,
    )

    assert json.loads(merged) == {"additional_context": "orientation"}


def test_cursor_merge_does_not_absorb_a_non_context_reply() -> None:
    permission = json.dumps({"permission": "allow"})
    orientation = json.dumps({"additional_context": "orientation"})

    assert (
        merge_allow_stdout(
            permission,
            orientation,
            "PreToolUse",
            cursor=True,
        )
        == permission + orientation
    )


def test_local_cursor_entry_marks_and_merges_client_orientation(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(local_entry, "parse_hook_payload", lambda _text: {})
    monkeypatch.setattr(
        local_entry,
        "record_client_anchor",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(local_entry, "detect_executor", lambda: "cursor")
    monkeypatch.setattr(
        local_entry,
        "record_then_stamp",
        lambda _payload, text, _executor, _event: text,
    )
    monkeypatch.setattr(
        local_entry,
        "ensure_user_lifecycle_hooks_for_executor",
        lambda _executor: None,
    )
    monkeypatch.setattr(
        local_entry,
        "capture_codex_session",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        local_entry,
        "relay_identity_payload",
        lambda *_a, **_k: {},
    )
    monkeypatch.setattr(local_entry, "resolve_capability", lambda _e: object())

    def run_event(_event, *, controls, **_kwargs):
        assert controls.payload_extra[CLIENT_ORIENTATION_PRESENT_KEY] is True
        controls.final_outcome = "allow"
        return json.dumps({"additional_context": "resume block"}), 0

    monkeypatch.setattr(local_entry, "run_event", run_event)

    rc = local_entry.evaluate_local_hook(
        "SessionStart",
        "{}",
        extra_context="orientation",
    )

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == {
        "additional_context": "orientation\n\nresume block",
    }
