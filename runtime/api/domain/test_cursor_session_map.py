"""Unit tests for the Cursor conversation-to-session mapping.

The mapping is the third rung of the ambient-identity chain, so these
cover both the store itself and its position in
``resolve_ambient_session_id`` — a rung that fired ahead of the ancestry
walk would hand a harness nested inside Cursor the Cursor session.
"""

from __future__ import annotations

import os
import time

import pytest

from yoke_contracts import session_identity
from yoke_contracts.cursor_session_map import (
    CURSOR_CONVERSATION_ENV_VAR,
    prune_stale_conversation_sessions,
    record_conversation_session,
    resolve_mapped_session_id,
)
from yoke_contracts.process_ancestry import ProcessAnchor


CONTAINER = "11111111-2222-3333-4444-555555555555"
SUBAGENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


@pytest.fixture()
def map_dir(tmp_path):
    return tmp_path / "cursor-session-map"


def _env(conversation_id: str) -> dict:
    return {CURSOR_CONVERSATION_ENV_VAR: conversation_id}


class TestRecordAndResolve:
    def test_a_subagent_conversation_resolves_to_its_container(self, map_dir):
        assert record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        resolved = resolve_mapped_session_id(map_dir, _env(SUBAGENT))
        assert resolved == CONTAINER

    def test_a_top_level_conversation_maps_to_itself(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        assert resolve_mapped_session_id(map_dir, _env(CONTAINER)) == CONTAINER

    def test_unrecorded_conversation_resolves_to_nothing(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        # The bare id is NOT the answer: a conversation no hook recorded
        # names no registered session, and guessing would attribute the
        # work to a row that does not exist.
        assert resolve_mapped_session_id(map_dir, _env(SUBAGENT)) is None

    def test_no_conversation_id_resolves_to_nothing(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        assert resolve_mapped_session_id(map_dir, {}) is None

    def test_missing_directory_resolves_to_nothing(self, tmp_path):
        assert resolve_mapped_session_id(tmp_path / "absent", _env(CONTAINER)) is None

    def test_empty_session_id_is_refused(self, map_dir):
        assert record_conversation_session(CONTAINER, "", map_dir) is False

    def test_ids_that_cannot_be_filenames_are_refused(self, map_dir):
        for unusable in ("../escape", "a/b", "", "x" * 129):
            assert record_conversation_session(unusable, CONTAINER, map_dir) is False
            assert resolve_mapped_session_id(map_dir, _env(unusable)) is None

    def test_corrupt_recording_resolves_to_nothing(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        (map_dir / f"{CONTAINER}.json").write_text("{not json", encoding="utf-8")
        assert resolve_mapped_session_id(map_dir, _env(CONTAINER)) is None


class TestStaleness:
    def _age(self, map_dir, conversation_id: str) -> None:
        entry = map_dir / f"{conversation_id}.json"
        ancient = time.time() - (400 * 24 * 3600)
        os.utime(entry, (ancient, ancient))

    def test_aged_out_recording_resolves_to_nothing_and_is_dropped(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        self._age(map_dir, CONTAINER)
        assert resolve_mapped_session_id(map_dir, _env(CONTAINER)) is None
        assert not (map_dir / f"{CONTAINER}.json").exists()

    def test_prune_drops_only_the_aged_out(self, map_dir):
        record_conversation_session(CONTAINER, CONTAINER, map_dir)
        record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        self._age(map_dir, SUBAGENT)
        assert prune_stale_conversation_sessions(map_dir) == 1
        assert (map_dir / f"{CONTAINER}.json").exists()
        assert not (map_dir / f"{SUBAGENT}.json").exists()

    def test_prune_on_a_missing_directory_is_a_no_op(self, tmp_path):
        assert prune_stale_conversation_sessions(tmp_path / "absent") == 0


class TestAmbientChainPosition:
    """Env, then ancestry, then the mapping — in that order."""

    def test_mapping_resolves_when_env_and_ancestry_are_empty(
        self, tmp_path, map_dir,
    ):
        record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        resolved = session_identity.resolve_ambient_session_id(
            tmp_path / "session-anchors", _env(SUBAGENT), cursor_map_dir=map_dir,
        )
        assert resolved == CONTAINER

    def test_env_chain_still_wins(self, tmp_path, map_dir):
        record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        env = {**_env(SUBAGENT), "YOKE_SESSION_ID": "pinned"}
        resolved = session_identity.resolve_ambient_session_id(
            tmp_path / "session-anchors", env, cursor_map_dir=map_dir,
        )
        assert resolved == "pinned"

    def test_a_nested_harness_keeps_its_own_anchored_identity(
        self, tmp_path, map_dir, monkeypatch,
    ):
        # A per-session harness launched inside a Cursor agent inherits
        # CURSOR_CONVERSATION_ID through the environment. Its own anchor,
        # which the ancestry walk reaches first, is the truthful answer.
        anchors_dir = tmp_path / "session-anchors"
        record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        session_identity.record_session_anchor(
            "nested-harness-session",
            anchors_dir,
            anchor=ProcessAnchor(
                pid=6161, start_time="s-6161", process_name="claude",
            ),
        )
        monkeypatch.setattr(
            session_identity, "anchor_candidate_pids",
            lambda _pid=None, parents=None, name_of=None: [6161],
        )
        monkeypatch.setattr(
            session_identity, "process_start_time", lambda _pid: "s-6161",
        )
        resolved = session_identity.resolve_ambient_session_id(
            anchors_dir, _env(SUBAGENT), cursor_map_dir=map_dir,
        )
        assert resolved == "nested-harness-session"

    def test_omitting_the_map_dir_skips_the_lane(self, tmp_path, map_dir):
        record_conversation_session(SUBAGENT, CONTAINER, map_dir)
        resolved = session_identity.resolve_ambient_session_id(
            tmp_path / "session-anchors", _env(SUBAGENT),
        )
        assert resolved is None
