"""session-begin lane resolution tests for yoke_core.api.service_client.

Sibling files:
- test_service_client_sessions_touch.py (session-touch)
- test_service_client_sessions_checkpoint.py (session-checkpoint)
- test_service_client_sessions_resolve.py (session-id auto-resolution)
- test_service_client_sessions_helpers.py (shared fixture + helpers)
"""

from __future__ import annotations

import json
import os

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_constants import TEST_MODEL_ID


class TestSessionBeginLane:
    """Verify session-begin resolves execution_lane from config."""

    def test_session_begin_resolves_lane_from_config_codex(self, session_offer_db):
        """Codex executor should resolve to ALTMAN via config."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_codex=ALTMAN\n")

        sid = "reg-lane-codex"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT execution_lane FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "ALTMAN"

    def test_session_begin_resolves_lane_from_config_claude_code(self, session_offer_db):
        """Claude Code executor should resolve to DARIUS via config."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_claude_code=DARIUS\n")

        sid = "reg-lane-claude"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT execution_lane FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "DARIUS"

    def test_session_begin_falls_back_to_primary_without_config(self, session_offer_db):
        """Unknown executor with no config mapping falls back to primary."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("")  # no lane mappings

        sid = "reg-lane-fallback"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "unknown-exec",
                "--provider", "test",
                "--model", "test-model",
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT execution_lane FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "primary"

    def test_session_begin_accepts_entrypoint_and_emits_it(self, session_offer_db):
        sid = "reg-entrypoint"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
                "--entrypoint", "codex-desktop",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'HarnessSessionStarted' AND session_id = %s ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        session_row = conn.execute(
            "SELECT executor, executor_display_name "
            "FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert session_row is not None
        # Canonical executor stored; surface alias preserved as display.
        assert session_row[0] == "codex"
        assert session_row[1] == "codex-desktop"
        envelope = json.loads(row[0])
        assert envelope["context"]["executor"] == "codex"
        assert envelope["context"]["executor_display_name"] == "codex-desktop"
        assert envelope["context"]["entrypoint"] == "codex-desktop"

    def test_session_begin_promotes_claude_executor_from_entrypoint_and_uses_project_lane(self, session_offer_db):
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_claude*=DARIUS\n")
            handle.write("executor_default_lane_claude_vscode=ALTMAN\n")

        sid = "reg-claude-surface"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
                "--entrypoint", "claude-vscode",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT executor, executor_display_name, execution_lane "
            "FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        event_row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'HarnessSessionStarted' AND session_id = %s ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        # Canonical executor stored; entrypoint-composed surface alias
        # lands in executor_display_name. The local config asks for
        # claude-vscode -> ALTMAN, but DB project routing is authoritative
        # once a project id is known.
        assert row[0] == "claude-code"
        assert row[1] == "claude-vscode"
        assert row[2] == "DARIUS"
        assert event_row is not None
        envelope = json.loads(event_row[0])
        assert envelope["context"]["executor"] == "claude-code"
        assert envelope["context"]["executor_display_name"] == "claude-vscode"
        assert envelope["context"]["entrypoint"] == "claude-vscode"

    def test_session_begin_promotes_legacy_claude_alias_from_entrypoint(self, session_offer_db):
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_claude_desktop=DARIUS\n")

        sid = "reg-legacy-claude"
        result = _run_client(
            [
                "session-begin",
                "--session-id", sid,
                "--executor", "claude",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--project-id", "1",
                "--entrypoint", "claude-desktop",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT executor, executor_display_name, execution_lane "
            "FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        event_row = conn.execute(
            "SELECT envelope FROM events WHERE event_name = 'HarnessSessionStarted' AND session_id = %s ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "claude-code"
        assert row[1] == "claude-desktop"
        assert row[2] == "DARIUS"
        assert event_row is not None
        envelope = json.loads(event_row[0])
        assert envelope["context"]["executor"] == "claude-code"
        assert envelope["context"]["executor_display_name"] == "claude-desktop"
        assert envelope["context"]["entrypoint"] == "claude-desktop"

    def test_session_begin_idempotent_on_existing_session(self, session_offer_db):
        """session-begin on an already-active session returns success."""
        sid = "begin-idempotent"
        args = [
            "session-begin",
            "--session-id", sid,
            "--executor", "claude-code",
            "--provider", "anthropic",
            "--model", "opus",
            "--workspace", session_offer_db["tmp_dir"],
            "--project-id", "1",
        ]
        r1 = _run_client(args, db_path=session_offer_db["db_path"])
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        d1 = json.loads(r1.stdout)
        assert d1["success"] is True

        # Second call should also succeed (idempotent)
        r2 = _run_client(args, db_path=session_offer_db["db_path"])
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)
        assert d2["success"] is True
        assert d2.get("already_registered") is True

    def test_session_begin_reactivates_ended_session(self, session_offer_db):
        """session-begin on an ended session reopens it as active.

        Executor is write-once.  The original executor value
        persists across reactivation; provider/model/lane refresh from the
        new register call.
        """
        sid = "begin-reactivate"
        first_args = [
            "session-begin",
            "--session-id", sid,
            "--executor", "claude-code",
            "--provider", "anthropic",
            "--model", "opus-old",
            "--workspace", session_offer_db["tmp_dir"],
            "--project-id", "1",
        ]
        r1 = _run_client(first_args, db_path=session_offer_db["db_path"])
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        first_data = json.loads(r1.stdout)
        original_offered_at = first_data["session"]["offered_at"]

        rend = _run_client(["session-end", "--session-id", sid], db_path=session_offer_db["db_path"])
        assert rend.returncode == 0, f"stderr: {rend.stderr}"

        second_args = [
            "session-begin",
            "--session-id", sid,
            "--executor", "codex",
            "--provider", "openai",
            "--model", "gpt-5.4",
            "--workspace", session_offer_db["tmp_dir"],
            "--project-id", "1",
        ]
        r2 = _run_client(second_args, db_path=session_offer_db["db_path"])
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)
        assert d2["success"] is True
        assert d2.get("already_registered") is not True

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT executor, provider, model, ended_at, offered_at FROM harness_sessions WHERE session_id = %s",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        # Stored executor is the original INSERT value, not the
        # second-call argument.  Provider/model/etc. still refresh.
        assert row[0] == "claude-code"
        assert row[1] == "openai"
        assert row[2] == "gpt-5.4"
        assert row[3] is None
        assert row[4] == original_offered_at
