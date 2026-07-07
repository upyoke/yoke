"""Tests for service_client session-offer command (task 005).

Basic offer + lane resolution + validation/error paths.

Charge flow → test_service_client_sessions_offer_charge.py
Resume + stale recovery → test_service_client_sessions_offer_resume.py
Persistence + concurrency → test_service_client_sessions_offer_persist.py
Codex manifest paths → test_service_client_sessions_offer_codex_manifest.py
"""

from __future__ import annotations

import json
import os

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_constants import TEST_MODEL_ID


class TestSessionOfferCommand:
    """Tests for service_client.py session-offer command (task 005)."""

    def test_session_offer_basic(self, session_offer_db):
        """session-offer returns valid NextAction JSON."""
        # pre-register session before offering
        sid = "offer-basic-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "action" in data
        assert "reason" in data
        assert "correlation_id" in data
        assert "chainable" in data

    def test_session_offer_custom_session_id(self, session_offer_db):
        """Custom --session-id is used as correlation_id."""
        sid = "my-custom-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["correlation_id"] == sid

    def test_session_offer_custom_lane(self, session_offer_db):
        """Custom --lane is accepted without error."""
        sid = "custom-lane-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "review",
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] in ("charge", "feed", "strategize", "escalate", "wait")

    def test_session_offer_uses_executor_default_lane_from_core_config(self, session_offer_db):
        """Omitted --lane resolves from explicit fixture config defaults."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_codex=ALTMAN\n")

        sid = "config-default-lane"
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
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

    def test_session_offer_default_lane_alias_uses_executor_default(self, session_offer_db):
        """Literal --lane default should still honor executor defaults."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_claude_code=DARIUS\n")

        sid = "config-default-alias"
        _pre_register_session(session_offer_db["db_path"], sid, executor="claude-code", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "claude-code",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--lane", "default",
                "--session-id", sid,
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

    def test_session_offer_lane_telemetry_uses_resolved_lane(self, session_offer_db):
        """Lane telemetry should record the resolved executor-default lane."""
        config_path = os.path.join(os.path.dirname(session_offer_db["db_path"]), "config")
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write("executor_default_lane_codex=ALTMAN\n")

        sid = "lane-telemetry-default"
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "codex",
                "--provider", "openai",
                "--model", "gpt-5.4",
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT envelope FROM events WHERE session_id = %s AND event_name = 'LaneRoutingDecision' ORDER BY id DESC LIMIT 1",
            (sid,),
        ).fetchone()
        conn.close()

        assert row is not None
        event = json.loads(row[0])
        assert event["context"]["actual_lane"] == "ALTMAN"

    def test_session_offer_missing_required_args(self, session_offer_db):
        """Missing required args exits with code 2."""
        result = _run_client(
            ["session-offer", "--executor", "DARIUS"],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 2

    def test_session_offer_auto_session_id_fails_without_pre_registered(self, session_offer_db):
        """auto-generated session ID fails because session-offer no longer creates sessions."""
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 1
        assert "No active session found" in result.stderr

    @pytest.mark.parametrize(
        "executor",
        ["claude-code", "claude-desktop", "codex", "codex-desktop"],
    )
    def test_session_offer_supported_harness_requires_session_id(self, session_offer_db, executor):
        """AC-6: supported harnesses must pass their canonical session ID."""
        from runtime.harness.hook_helpers import is_codex
        result = _run_client(
            [
                "session-offer",
                "--executor", executor,
                "--provider", "openai" if is_codex(executor) else "anthropic",
                "--model", "gpt-5.4" if is_codex(executor) else TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 1
        assert "--session-id" in result.stderr
        assert "canonical harness session ID" in result.stderr
        assert "Auto-generating a fallback ID is not allowed" in result.stderr
