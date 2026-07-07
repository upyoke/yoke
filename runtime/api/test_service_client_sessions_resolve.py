"""Session-ID auto-resolution tests for yoke_core.api.service_client.

Shared fixture/helpers live in ``test_service_client_sessions_helpers.py``.
"""

from __future__ import annotations

import json
import os
import subprocess

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _run_client,
    _service_client_cmd,
    _with_source_pythonpath,
)
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestResolveSessionId:
    """Unit tests for _resolve_session_id (AC-1 through AC-4)."""

    def test_explicit_value_returned_as_is(self, monkeypatch):
        """AC-4: explicit value wins regardless of env vars."""
        monkeypatch.setenv("YOKE_SESSION_ID", "env-value")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id("explicit-value") == "explicit-value"

    def test_yoke_session_id_env(self, monkeypatch):
        """AC-1: YOKE_SESSION_ID is the first env fallback."""
        monkeypatch.setenv("YOKE_SESSION_ID", "yoke-sid")
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "yoke-sid"

    def test_claude_session_id_fallback(self, monkeypatch):
        """AC-2: CLAUDE_SESSION_ID is the second env fallback."""
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-sid")
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "claude-sid"

    def test_codex_thread_id_fallback(self, monkeypatch):
        """AC-3: CODEX_THREAD_ID is the third env fallback."""
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-tid")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "codex-tid"

    def test_none_when_nothing_set(self, monkeypatch):
        """Returns None when no explicit value and no env vars."""
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) is None

    def test_empty_string_treated_as_missing(self, monkeypatch):
        """Empty explicit value falls through to env vars."""
        monkeypatch.setenv("YOKE_SESSION_ID", "env-val")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id("") == "env-val"

    def test_priority_yoke_over_claude(self, monkeypatch):
        """YOKE_SESSION_ID takes priority over CLAUDE_SESSION_ID."""
        monkeypatch.setenv("YOKE_SESSION_ID", "yoke-wins")
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-loses")
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-loses")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "yoke-wins"


class TestSessionIdAutoResolutionIntegration:
    """Integration tests: commands work without --session-id when env var is set (AC-5 through AC-7)."""

    def test_session_touch_uses_env_session_id(self, session_offer_db):
        """AC-5: session-touch resolves session ID from env."""
        db = session_offer_db["db_path"]
        sid = "env-touch-test"
        # Create session first
        r = _run_client(
            ["session-begin", "--session-id", sid,
             "--executor", "claude-code", "--provider", "anthropic",
             "--model", "opus", "--workspace", session_offer_db["tmp_dir"],
             "--project-id", "1"],
            db_path=db,
        )
        assert r.returncode == 0

        # Touch without --session-id, using env var
        env = os.environ.copy()
        env["YOKE_DB"] = db
        env["YOKE_SESSION_ID"] = sid
        r2 = subprocess.run(
            _service_client_cmd(["session-touch"]),
            capture_output=True, text=True, env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT, timeout=30,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        data = json.loads(r2.stdout)
        assert data["success"] is True

    def test_session_touch_explicit_overrides_env(self, session_offer_db):
        """AC-6: explicit --session-id still works and overrides env."""
        db = session_offer_db["db_path"]
        sid = "explicit-override-test"
        r = _run_client(
            ["session-begin", "--session-id", sid,
             "--executor", "claude-code", "--provider", "anthropic",
             "--model", "opus", "--workspace", session_offer_db["tmp_dir"],
             "--project-id", "1"],
            db_path=db,
        )
        assert r.returncode == 0

        # Use explicit --session-id even though a different env var is set
        env = os.environ.copy()
        env["YOKE_DB"] = db
        env["YOKE_SESSION_ID"] = "wrong-session"
        r2 = subprocess.run(
            _service_client_cmd(["session-touch", "--session-id", sid]),
            capture_output=True, text=True, env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT, timeout=30,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"

    def test_claim_item_uses_env_session_id(self, session_offer_db):
        """AC-5: claim-work resolves session ID from env."""
        db = session_offer_db["db_path"]
        sid = "env-claim-test"
        # Create session
        conn = connect_test_db(db)
        conn.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, "
            "project_id, execution_lane, workspace, mode, offered_at, last_heartbeat) "
            "VALUES (%s, 'claude-code', 'anthropic', 'opus', 1, 'primary', %s, 'hook', "
            "'2026-04-20T00:00:00Z', '2026-04-20T00:00:00Z')",
            (sid, session_offer_db["tmp_dir"]),
        )
        conn.commit()
        conn.close()

        # Claim without --session-id, using env var
        env = os.environ.copy()
        env["YOKE_DB"] = db
        env["YOKE_SESSION_ID"] = sid
        r = subprocess.run(
            _service_client_cmd(["claim-work", "--item", "YOK-10"]),
            capture_output=True, text=True, env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT, timeout=30,
        )
        assert r.returncode == 0, f"stderr: {r.stderr}"
        data = json.loads(r.stdout)
        assert data["success"] is True

    def test_missing_session_id_exits_2(self):
        """AC-7: commands exit 2 with clear error when no session ID can be resolved."""
        # Clear all session env vars
        env = os.environ.copy()
        for var in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
            env.pop(var, None)

        commands_requiring_session_id = [
            ["session-touch"],
            ["session-heartbeat"],
            ["session-begin", "--executor", "e", "--provider", "p", "--model", "m", "--workspace", "w"],
            ["session-end"],
            ["session-end-if-empty"],
            ["claim-work", "--item", "YOK-1"],
            ["release-work-claim", "--item", "YOK-1", "--reason", "test"],
            ["release-all-claims", "--reason", "test"],
            ["session-checkpoint", "--step", "1", "--action", "a", "--chainable", "true"],
            ["session-checkpoint-read"],
        ]

        for cmd_args in commands_requiring_session_id:
            r = subprocess.run(
                _service_client_cmd(cmd_args),
                capture_output=True, text=True, env=_with_source_pythonpath(env),
                cwd=_REPO_ROOT, timeout=30,
            )
            assert r.returncode == 2, (
                f"Expected exit 2 for {cmd_args[0]} without session ID, "
                f"got {r.returncode}. stderr: {r.stderr}"
            )
            # The denial is an infrastructure-bug signal naming the
            # operator-debug override; it must NOT teach env-var
            # self-bootstrap (no env var names in the message).
            assert "infrastructure gap" in r.stderr, (
                f"{cmd_args[0]} should frame the missing ambient session "
                f"as an infrastructure gap. stderr: {r.stderr}"
            )
            assert "--session-id" in r.stderr, (
                f"{cmd_args[0]} should name the operator-debug override. "
                f"stderr: {r.stderr}"
            )
            assert "YOKE_SESSION_ID" not in r.stderr, (
                f"{cmd_args[0]} must not teach env-var self-bootstrap. "
                f"stderr: {r.stderr}"
            )

    def test_claude_session_id_fallback_works(self, session_offer_db):
        """AC-2/AC-5: CLAUDE_SESSION_ID fallback works for session-touch."""
        db = session_offer_db["db_path"]
        sid = "claude-fallback-test"
        r = _run_client(
            ["session-begin", "--session-id", sid,
             "--executor", "claude-code", "--provider", "anthropic",
             "--model", "opus", "--workspace", session_offer_db["tmp_dir"],
             "--project-id", "1"],
            db_path=db,
        )
        assert r.returncode == 0

        env = os.environ.copy()
        env["YOKE_DB"] = db
        env.pop("YOKE_SESSION_ID", None)
        env["CLAUDE_SESSION_ID"] = sid
        env.pop("CODEX_THREAD_ID", None)
        r2 = subprocess.run(
            _service_client_cmd(["session-touch"]),
            capture_output=True, text=True, env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT, timeout=30,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
