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
HOLDER = "99999999-8888-7777-6666-555555555555"
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
        cursor_session_map.record_conversation_session(CONTAINER, CONTAINER)
        cursor_session_map.record_from_hook_payload(_payload(), "cursor")
        assert _mapped(machine_home, SUBAGENT) == CONTAINER

    def test_folded_payload_still_records_the_child_alias(self, machine_home):
        # Payload adapter folds session_id onto the container and parks the
        # child on subagent_session_id; shells still export the child id.
        cursor_session_map.record_conversation_session(CONTAINER, CONTAINER)
        cursor_session_map.record_from_hook_payload(
            {
                "hook_event_name": "beforeShellExecution",
                "session_id": CONTAINER,
                "conversation_id": SUBAGENT,
                "subagent_session_id": SUBAGENT,
            },
            "cursor",
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_top_level_session_start_records_against_itself(self, machine_home):
        cursor_session_map.record_from_hook_payload(
            _payload(CONTAINER), "cursor", "SessionStart",
        )
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_mapped_transcript_container_keeps_registered_session(
        self, machine_home,
    ):
        cursor_session_map.record_conversation_session(CONTAINER, HOLDER)
        cursor_session_map.record_from_hook_payload(
            _payload(CONTAINER), "cursor", "PreToolUse",
        )
        assert _mapped(machine_home, CONTAINER) == HOLDER

    def test_pretooluse_top_level_transcript_self_maps(
        self, machine_home,
    ):
        cursor_session_map.record_from_hook_payload(
            _payload(CONTAINER), "cursor", "PreToolUse",
        )
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_other_harnesses_record_nothing(self, machine_home):
        cursor_session_map.record_from_hook_payload(_payload(), "claude-code")
        assert _mapped(machine_home, SUBAGENT) is None

    def test_pretooluse_top_level_without_transcript_self_maps(
        self, machine_home, monkeypatch,
    ):
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR)
        cursor_session_map.record_from_hook_payload(
            _payload(CONTAINER), "cursor", "PreToolUse",
        )
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_session_start_records_itself_without_evidence(
        self, machine_home, monkeypatch,
    ):
        # Cursor leaves the transcript path empty through a fresh session's
        # first events, so without this the session's FIRST command has no
        # identity at all. Session start fires once, for the top level.
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR)
        cursor_session_map.record_from_hook_payload(
            {"session_id": CONTAINER}, "cursor", "SessionStart",
        )
        assert _mapped(machine_home, CONTAINER) == CONTAINER

    def test_session_start_still_prefers_evidence_over_its_own_id(
        self, machine_home,
    ):
        # A sub-conversation naming its parent must not map to itself.
        cursor_session_map.record_conversation_session(CONTAINER, CONTAINER)
        cursor_session_map.record_from_hook_payload(
            _payload(), "cursor", "SessionStart",
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER

    def test_session_start_without_roots_does_not_clobber_worktree_fold(
        self, machine_home, monkeypatch,
    ):
        # Live smoke: worktree sessionStart folds onto the claim holder, then
        # a later sessionStart without workspace_roots used to rewrite the
        # map to identity and break ambient resolution.
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR, raising=False)
        remapped = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
        cursor_session_map.record_conversation_session(remapped, CONTAINER)
        assert _mapped(machine_home, remapped) == CONTAINER
        cursor_session_map.record_from_hook_payload(
            {"session_id": remapped, "conversation_id": remapped},
            "cursor",
            "SessionStart",
        )
        assert _mapped(machine_home, remapped) == CONTAINER


    def test_pretooluse_subagent_layout_folds_to_parent(
        self, machine_home, monkeypatch,
    ):
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR, raising=False)
        monkeypatch.setattr(
            cursor_session_map,
            "resolve_container_from_subagent_transcript_layout",
            lambda cid, **_k: CONTAINER if cid == SUBAGENT else "",
        )
        cursor_session_map.record_from_hook_payload(
            _payload(SUBAGENT), "cursor", "PreToolUse",
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER
        assert _mapped(machine_home, CONTAINER) is None

    def test_pretooluse_worktree_holder_folds_to_holder(
        self, machine_home, monkeypatch,
    ):
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR, raising=False)
        monkeypatch.setattr(
            cursor_session_map, "_worktree_remap_container", lambda _p: HOLDER,
        )
        cursor_session_map.record_from_hook_payload(
            {
                **_payload(CONTAINER),
                "workspace_roots": ["/repo/.worktrees/YOK-1"],
            },
            "cursor",
            "PreToolUse",
        )
        assert _mapped(machine_home, CONTAINER) == HOLDER

    def test_pretooluse_worktree_without_holder_does_not_self_map(
        self, machine_home, monkeypatch,
    ):
        monkeypatch.delenv(CURSOR_TRANSCRIPT_ENV_VAR, raising=False)
        monkeypatch.setattr(
            cursor_session_map, "_worktree_remap_container", lambda _p: "",
        )
        cursor_session_map.record_from_hook_payload(
            {
                **_payload(CONTAINER),
                "workspace_roots": ["/repo/.worktrees/YOK-1"],
            },
            "cursor",
            "PreToolUse",
        )
        assert _mapped(machine_home, CONTAINER) is None



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
        cursor_session_map.record_conversation_session(CONTAINER, CONTAINER)
        relay.evaluate_hook_event(
            "PreToolUse", stdin_data=json.dumps(_payload()),
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER

    def test_https_relay_records_client_side(self, machine_home):
        # The denial short-circuits before any network call; the recording
        # must already have happened, because the relayed evaluation runs
        # on a machine this shell will never read a mapping from.
        cursor_session_map.record_conversation_session(CONTAINER, CONTAINER)
        relay.relay_hook_event(
            "PreToolUse", object(), stdin_data=json.dumps(_payload()),
        )
        assert _mapped(machine_home, SUBAGENT) == CONTAINER
