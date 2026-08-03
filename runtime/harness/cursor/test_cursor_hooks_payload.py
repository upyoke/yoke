"""Unit tests for Cursor hook payload parsing and canonicalization.

Payload fixtures mirror the wire shape of Cursor IDE 3.14.7 /
cursor-agent 2026.07.23: every event carries ``session_id`` +
``conversation_id`` (equal values), shell gates carry a top-level
``command``, and subagent activity arrives under the subagent's own
session id with the container recoverable from the
``CURSOR_TRANSCRIPT_PATH`` env var or ``parent_conversation_id``.
"""

from __future__ import annotations

import json

import pytest

from runtime.harness.cursor.cursor_hooks_payload import (
    parse_payload,
    payload_field,
    resolve_container_session_id,
    resolve_root,
    resolve_session_id,
)

MAIN = "11111111-2222-3333-4444-555555555555"
SUB = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TRANSCRIPT = f"/home/u/.cursor/projects/p/agent-transcripts/{MAIN}/{MAIN}.jsonl"


@pytest.fixture
def container_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.setenv("CURSOR_TRANSCRIPT_PATH", TRANSCRIPT)


@pytest.fixture
def bare_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    monkeypatch.delenv("CURSOR_TRANSCRIPT_PATH", raising=False)
    monkeypatch.delenv("CURSOR_PROJECT_DIR", raising=False)
    monkeypatch.delenv("YOKE_ROOT", raising=False)


def test_shell_gate_synthesizes_bash_tool_shape(container_env: None) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "beforeShellExecution",
            "command": "echo hi",
            "sandbox": "enabled",
            "session_id": MAIN,
            "conversation_id": MAIN,
        }
    )
    data = parse_payload(payload)
    assert data["tool_name"] == "Bash"
    assert data["tool_input"]["command"] == "echo hi"
    assert data["container_session_id"] == MAIN
    assert data["is_subagent_session"] is False


def test_after_shell_maps_output_to_tool_output(container_env: None) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "afterShellExecution",
            "command": "ls",
            "output": "file1",
            "session_id": MAIN,
        }
    )
    data = parse_payload(payload)
    assert data["tool_name"] == "Bash"
    assert data["tool_output"] == "file1"


def test_shell_tool_name_canonicalizes_to_bash(container_env: None) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "preToolUse",
            "tool_name": "Shell",
            "tool_input": {"command": "ls"},
            "session_id": MAIN,
        }
    )
    assert parse_payload(payload)["tool_name"] == "Bash"


def test_non_shell_tool_names_pass_through(container_env: None) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "preToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/x"},
            "session_id": MAIN,
        }
    )
    assert parse_payload(payload)["tool_name"] == "Read"


def test_subagent_event_folds_into_container(container_env: None) -> None:
    payload = json.dumps(
        {
            "hook_event_name": "preToolUse",
            "tool_name": "Read",
            "session_id": SUB,
            "conversation_id": SUB,
        }
    )
    data = parse_payload(payload)
    assert data["container_session_id"] == MAIN
    assert data["is_subagent_session"] is True
    # session_id rewrites to the container so downstream consumers
    # attribute to the top-level session; the subagent's own id survives.
    assert data["session_id"] == MAIN
    assert data["subagent_session_id"] == SUB


def test_parent_conversation_id_wins_without_env(bare_env: None) -> None:
    data = {"session_id": SUB, "parent_conversation_id": MAIN}
    assert resolve_container_session_id(data) == MAIN


def test_own_session_is_container_fallback(bare_env: None) -> None:
    data = {"session_id": MAIN, "conversation_id": MAIN}
    assert resolve_container_session_id(data) == MAIN


def test_resolve_session_id_pin_wins(
    container_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = json.dumps({"session_id": MAIN})
    monkeypatch.setenv("YOKE_SESSION_ID", "pinned")
    assert resolve_session_id(payload) == "pinned"
    monkeypatch.delenv("YOKE_SESSION_ID")
    assert resolve_session_id(payload) == MAIN


def test_resolve_root_order(bare_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    both = json.dumps({"workspace_roots": ["/ws"], "cwd": "/cwd"})
    assert resolve_root(both) == "/ws"
    assert resolve_root(json.dumps({"cwd": "/cwd"})) == "/cwd"
    monkeypatch.setenv("CURSOR_PROJECT_DIR", "/proj")
    assert resolve_root("") == "/proj"


def _mapped(machine_home, conversation_id: str) -> str | None:
    from yoke_contracts.cursor_session_map import (
        CURSOR_CONVERSATION_ENV_VAR,
        CURSOR_SESSION_MAP_DIR_NAME,
        resolve_mapped_session_id,
    )

    return resolve_mapped_session_id(
        machine_home / CURSOR_SESSION_MAP_DIR_NAME,
        {CURSOR_CONVERSATION_ENV_VAR: conversation_id},
    )


@pytest.fixture
def machine_home(tmp_path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_parsing_records_the_conversation_to_container_pairing(
    container_env: None, machine_home
) -> None:
    # Without this recording a shell the subagent runs carries only SUB,
    # which names no registered session — the identity failure the mapping
    # exists to close.
    parse_payload(json.dumps({
        "hook_event_name": "beforeShellExecution",
        "command": "yoke items get X",
        "session_id": SUB,
        "conversation_id": SUB,
    }))
    assert _mapped(machine_home, SUB) == MAIN


def test_parsing_a_top_level_event_records_the_session_against_itself(
    container_env: None, machine_home
) -> None:
    parse_payload(json.dumps({
        "hook_event_name": "sessionStart",
        "session_id": MAIN,
        "conversation_id": MAIN,
    }))
    assert _mapped(machine_home, MAIN) == MAIN


def test_no_pairing_recorded_without_evidence_of_the_container(
    bare_env: None, machine_home
) -> None:
    # With no transcript path and no parent id, this event's own id might
    # be the container or might be a sub-conversation. A wrong pairing is
    # worse than a missing one.
    parse_payload(json.dumps({
        "hook_event_name": "preToolUse",
        "tool_name": "Read",
        "session_id": SUB,
        "conversation_id": SUB,
    }))
    assert _mapped(machine_home, SUB) is None


def test_garbage_and_field_stringification(bare_env: None) -> None:
    assert parse_payload("") == {}
    assert parse_payload("not json") == {}
    assert parse_payload("[1,2]") == {}
    assert payload_field(json.dumps({"is_background_agent": False}), "is_background_agent") == "false"
    assert payload_field(json.dumps({"x": None}), "x") == ""
