"""The Cursor conversation mapping is written by the CLIENT hook process.

Which side writes it is the whole point, and is not something a unit test
of the recorder alone can show. Over https the harness payload adapter —
the obvious-looking home for this, since it already resolves the container
— is evaluated on the server, where the transcript env does not exist and
the machine home belongs to the server rather than to the shell that will
later read the mapping. So both client entry points are asserted to record.
"""

from __future__ import annotations

import json

import pytest

from yoke_harness.hooks import cursor_session_map, relay
from yoke_harness.hooks.local_subset import LocalSubsetEvaluation
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    CURSOR_SESSION_MAP_DIR_NAME,
    CURSOR_TRANSCRIPT_ENV_VAR,
    resolve_mapped_session_id,
)


CONTAINER = "11111111-2222-3333-4444-555555555555"
SUBAGENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
TRANSCRIPT = (
    f"/home/u/.cursor/projects/p/agent-transcripts/{CONTAINER}/{CONTAINER}.jsonl"
)


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setenv(CURSOR_TRANSCRIPT_ENV_VAR, TRANSCRIPT)
    return home


def _mapped(machine_home, conversation_id: str):
    return resolve_mapped_session_id(
        machine_home / CURSOR_SESSION_MAP_DIR_NAME,
        {CURSOR_CONVERSATION_ENV_VAR: conversation_id},
    )


def _payload(session_id: str = SUBAGENT) -> dict:
    return {
        "hook_event_name": "beforeShellExecution",
        "command": "yoke items get X",
        "session_id": session_id,
        "conversation_id": session_id,
    }


class TestRecorder:
    def test_subagent_conversation_records_against_the_container(
        self, machine_home,
    ):
        cursor_session_map.record_from_hook_payload(_payload(), "cursor")
        assert _mapped(machine_home, SUBAGENT) == CONTAINER

    def test_top_level_conversation_records_against_itself(self, machine_home):
        cursor_session_map.record_from_hook_payload(_payload(CONTAINER), "cursor")
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_other_harnesses_record_nothing(self, machine_home):
        cursor_session_map.record_from_hook_payload(_payload(), "claude-code")
        assert _mapped(machine_home, SUBAGENT) is None

    def test_nothing_recorded_without_evidence_of_the_container(
        self, machine_home, monkeypatch,
    ):
        # Own id might be the container or might be a sub-conversation.
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR)
        cursor_session_map.record_from_hook_payload(_payload(), "cursor")
        assert _mapped(machine_home, SUBAGENT) is None


class TestClientEntryPoints:
    """Both hook entry points record, before anything can short-circuit."""

    @pytest.fixture(autouse=True)
    def _client_side_only(self, monkeypatch):
        monkeypatch.setattr(relay, "detect_executor", lambda: "cursor")
        monkeypatch.setattr(relay, "_client_lint_config_snapshot", lambda _p: {})
        monkeypatch.setattr(relay, "_record_client_anchor", lambda *_a, **_k: None)
        monkeypatch.setattr(relay, "_codex_capture", lambda *_a: None)
        monkeypatch.setattr(
            relay, "evaluate_local_subset",
            lambda *_a, **_k: LocalSubsetEvaluation(stdout="", exit_code=2, denied=True),
        )

    def test_local_evaluation_records(self, machine_home):
        relay.evaluate_hook_event(
            "PreToolUse", stdin_data=json.dumps(_payload()),
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER

    def test_https_relay_records_client_side(self, machine_home):
        # The denial short-circuits before any network call; the recording
        # must already have happened, because the relayed evaluation runs
        # on a machine this shell will never read a mapping from.
        relay.relay_hook_event(
            "PreToolUse", object(), stdin_data=json.dumps(_payload()),
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER
