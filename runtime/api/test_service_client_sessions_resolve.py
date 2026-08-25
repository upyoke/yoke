"""Session-ID auto-resolution tests for yoke_core.api.service_client.

Shared fixture/helpers live in ``test_service_client_sessions_helpers.py``.
"""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally re-exported.

from __future__ import annotations

import json
import os
import subprocess

import pytest

from yoke_contracts.harness_family_identity import (
    CLAUDE_FAMILY,
    nearest_harness_family,
)
from yoke_contracts.session_identity import AMBIENT_ENV_VARS
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


def _clear_chain(monkeypatch):
    for name in AMBIENT_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


#: A subprocess inherits this suite's process tree, so it belongs to
#: whichever harness family is running the tests. One started from
#: another harness correctly refuses an injected Claude variable — the
#: behaviour under test elsewhere, not a failure here.
_CLAUDE_LANE_REACHABLE = nearest_harness_family() in (None, CLAUDE_FAMILY)


class TestResolveSessionId:
    """Unit tests for _resolve_session_id."""

    @pytest.fixture(autouse=True)
    def family_blind(self, monkeypatch):
        """Describe a process with no harness above it.

        Ambient resolution is scoped to the harness family the process
        tree names, so these chain-order assertions are about the
        family-blind fallback — an operator terminal, CI, a reparented
        process. Without the pin they would answer for whichever harness
        happens to be running the suite.
        """
        from yoke_core.domain import session_ambient_identity

        monkeypatch.setattr(
            session_ambient_identity, "nearest_harness_family",
            lambda *_a, **_k: None,
        )

    def test_explicit_value_returned_as_is(self, monkeypatch):
        """Explicit value wins regardless of env vars."""
        monkeypatch.setenv("YOKE_SESSION_ID", "env-value")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id("explicit-value") == "explicit-value"

    @pytest.mark.parametrize("var,value", list(zip(AMBIENT_ENV_VARS, (
        "yoke-sid", "claude-sid", "codex-parent-sid", "codex-tid",
    ))))
    def test_each_chain_variable_resolves_alone(self, monkeypatch, var, value):
        """Every chain variable resolves when it is the only one set."""
        _clear_chain(monkeypatch)
        monkeypatch.setenv(var, value)
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == value

    def test_codex_parent_outranks_subagent_thread(self, monkeypatch):
        """A Codex subagent shell resolves to the parent, not its own thread."""
        _clear_chain(monkeypatch)
        monkeypatch.setenv("CODEX_SESSION_ID", "codex-parent")
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-child")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "codex-parent"

    def test_none_when_nothing_set(self, monkeypatch):
        """Returns None when no explicit value and no env vars."""
        _clear_chain(monkeypatch)
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) is None

    def test_empty_string_treated_as_missing(self, monkeypatch):
        """Empty explicit value falls through to env vars."""
        monkeypatch.setenv("YOKE_SESSION_ID", "env-val")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id("") == "env-val"

    def test_priority_yoke_over_claude(self, monkeypatch):
        """YOKE_SESSION_ID takes priority over CLAUDE_CODE_SESSION_ID."""
        monkeypatch.setenv("YOKE_SESSION_ID", "yoke-wins")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-loses")
        monkeypatch.setenv("CODEX_THREAD_ID", "codex-loses")
        from yoke_core.api.service_client import _resolve_session_id
        assert _resolve_session_id(None) == "yoke-wins"


class TestSessionIdAutoResolutionIntegration:
    """Integration tests: commands work without --session-id when env var is set."""

    def test_session_touch_uses_env_session_id(self, session_offer_db):
        """Session-touch resolves session ID from env."""
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
        """Explicit --session-id still works and overrides env."""
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
        """Claim-work resolves session ID from env."""
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
        """Commands exit 2 with clear error when no session ID can be resolved."""
        # Clear all session env vars
        env = os.environ.copy()
        for var in AMBIENT_ENV_VARS:
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

    @pytest.mark.skipif(
        not _CLAUDE_LANE_REACHABLE,
        reason="suite runs under a harness whose family is not Claude",
    )
    def test_claude_session_id_fallback_works(self, session_offer_db):
        """CLAUDE_CODE_SESSION_ID fallback works for session-touch."""
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
        env["CLAUDE_CODE_SESSION_ID"] = sid
        env.pop("CODEX_THREAD_ID", None)
        r2 = subprocess.run(
            _service_client_cmd(["session-touch"]),
            capture_output=True, text=True, env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT, timeout=30,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
