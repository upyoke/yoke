"""Tests for runtime.harness.harness_sessions."""
from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain import db_backend


TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestHarnessSessions:
    def test_begin_and_list(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_list
        result = cmd_begin(test_db, "sess-1", "claude", "anthropic",
                           "opus-4", "/workspace")
        assert "Began session" in result

        listed = cmd_list(test_db)
        assert "sess-1" in listed

    def test_touch(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_touch
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        result = cmd_touch(test_db, "s1")
        assert "Heartbeat" in result

    def test_claim_and_release(self, test_db):
        from runtime.harness.harness_sessions import (
            cmd_begin,
            cmd_claim,
            cmd_list_claims,
            cmd_release,
        )
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        result = cmd_claim(test_db, "s1", "item", item_id=TEST_ITEM_ID)
        assert "Claimed" in result

        claims = cmd_list_claims(test_db, "s1")
        assert str(TEST_ITEM_ID) in claims

        # Get claim ID from DB
        row = test_db.execute("SELECT id FROM work_claims LIMIT 1").fetchone()
        release_result = cmd_release(test_db, row[0], "completed")
        assert "Released" in release_result

    def test_idempotent_claim(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_claim
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        cmd_claim(test_db, "s1", "item", item_id=TEST_ITEM_ID)
        result = cmd_claim(test_db, "s1", "item", item_id=TEST_ITEM_ID)
        assert "already owned" in result

    def test_end_session(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_end, cmd_list
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        cmd_end(test_db, "s1")
        listed = cmd_list(test_db)
        assert "s1" not in listed

    def test_who_claims(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_claim, cmd_who_claims
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        cmd_claim(test_db, "s1", "item", item_id=10)
        result = cmd_who_claims(test_db, "YOK-10")
        assert "s1" in result
        assert "10" in result

    def test_get(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_get
        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        result = cmd_get(test_db, "s1")
        assert "claude" in result
        assert "opus" in result

    @patch("yoke_core.domain.events.emit_event")
    def test_claim_promotes_top_level_item_id(self, mock_emit, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_claim

        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        cmd_claim(test_db, "s1", "item", item_id=TEST_ITEM_ID)

        args, kwargs = mock_emit.call_args
        assert args[0] == "WorkClaimed"
        assert kwargs["item_id"] == str(TEST_ITEM_ID)
        assert kwargs["context"]["detail"]["item_id"] == str(TEST_ITEM_ID)

    @patch("yoke_core.domain.events.emit_event")
    def test_release_promotes_top_level_item_id(self, mock_emit, test_db):
        from runtime.harness.harness_sessions import cmd_begin, cmd_claim, cmd_release

        cmd_begin(test_db, "s1", "claude", "anthropic", "opus", "/ws")
        cmd_claim(test_db, "s1", "item", item_id=TEST_ITEM_ID)
        row = test_db.execute("SELECT id FROM work_claims LIMIT 1").fetchone()

        mock_emit.reset_mock()
        cmd_release(test_db, row[0], "completed")

        args, kwargs = mock_emit.call_args
        assert args[0] == "WorkReleased"
        assert kwargs["item_id"] == str(TEST_ITEM_ID)
        assert kwargs["context"]["detail"]["claim_id"] == row[0]


class TestCmdBeginCanonicalizesExecutor:
    def _stored_executor(self, conn, session_id):
        row = conn.execute(
            "SELECT executor, executor_display_name "
            f"FROM harness_sessions WHERE session_id = {_p(conn)}",
            (session_id,),
        ).fetchone()
        return row[0], row[1]

    def test_surface_specific_inbound_is_canonicalized(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin

        cases = [
            ("claude-desktop", "claude-code", "claude-desktop"),
            ("claude-vscode", "claude-code", "claude-vscode"),
            ("codex-desktop", "codex", "codex-desktop"),
        ]
        for idx, (inbound, want_canonical, want_display) in enumerate(cases):
            sid = f"sess-canonicalize-{idx}"
            cmd_begin(test_db, sid, inbound, "anthropic", "opus", "/ws")
            executor, display = self._stored_executor(test_db, sid)
            assert executor == want_canonical, (inbound, executor)
            assert display == want_display, (inbound, display)

    def test_canonical_inbound_keeps_display_null(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin

        cmd_begin(test_db, "sess-canonical", "claude-code", "anthropic",
                  "opus", "/ws")
        executor, display = self._stored_executor(test_db, "sess-canonical")
        assert executor == "claude-code"
        assert display is None

    def test_unknown_executor_passes_through_with_null_display(self, test_db):
        from runtime.harness.harness_sessions import cmd_begin

        cmd_begin(test_db, "sess-custom", "my-custom-tool", "anthropic",
                  "opus", "/ws")
        executor, display = self._stored_executor(test_db, "sess-custom")
        assert executor == "my-custom-tool"
        assert display is None

    @patch("runtime.harness.harness_sessions_lifecycle._emit_event")
    def test_event_payload_includes_display_name(self, mock_emit, test_db):
        from runtime.harness.harness_sessions import cmd_begin
        import json

        cmd_begin(test_db, "sess-evt", "claude-desktop", "anthropic",
                  "opus", "/ws")
        payload = json.loads(mock_emit.call_args.args[3])
        assert payload["executor"] == "claude-code"
        assert payload["executor_display_name"] == "claude-desktop"

    @patch("runtime.harness.harness_sessions_lifecycle._emit_event")
    def test_event_payload_omits_display_when_null(self, mock_emit, test_db):
        from runtime.harness.harness_sessions import cmd_begin
        import json

        cmd_begin(test_db, "sess-evt-noalias", "claude-code", "anthropic",
                  "opus", "/ws")
        payload = json.loads(mock_emit.call_args.args[3])
        assert payload["executor"] == "claude-code"
        assert "executor_display_name" not in payload
