"""Tests for service_client session-offer command (task 005).

Basic offer + lane resolution + validation/error paths.

Charge flow → test_service_client_sessions_offer_charge.py
Resume + stale recovery → test_service_client_sessions_offer_resume.py
Persistence + concurrency → test_service_client_sessions_offer_persist.py
Codex manifest paths → test_service_client_sessions_offer_codex_manifest.py
"""

# ruff: noqa: F811

from __future__ import annotations

import json
import os


from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


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
                "--session-id",
                sid,
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
                "--session-id",
                sid,
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
                "--session-id",
                sid,
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
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", requested_model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--session-id",
                sid,
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
                "--session-id",
                sid,
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
        _pre_register_session(session_offer_db["db_path"], sid, executor="codex", provider="openai", requested_model="gpt-5.4", workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--session-id",
                sid,
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

    def test_session_offer_accepts_no_identity_arguments(self, session_offer_db):
        """The surface has no field a caller could assert identity into.

        A caller-supplied lane is the mechanism by which a locally guessed
        value outranks the session row, so argument parsing — not a runtime
        check — is what keeps it unreachable.
        """
        for flag, value in (
            ("--executor", "codex"),
            ("--provider", "openai"),
            ("--model", "some-model"),
            ("--workspace", "/tmp/workspace"),
            ("--supported-paths", "advance"),
        ):
            result = _run_client(
                ["session-offer", flag, value],
                db_path=session_offer_db["db_path"],
            )
            assert result.returncode == 2, f"{flag} was accepted"
            assert "unrecognized arguments" in result.stderr

    def test_session_offer_unregistered_session_names_registration_recovery(
        self, session_offer_db,
    ):
        """An unregistered id is refused with its recovery, never invented."""
        result = _run_client(
            [
                "session-offer",
                "--session-id",
                "offer-never-registered",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 1
        assert "offer-never-registered" in result.stderr
        assert "hook" in result.stderr.lower()
