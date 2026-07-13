"""In-process session lifecycle for a bound local-postgres universe.

Covers the engine-side orchestrator the ``yoke hook evaluate`` adapter drives
when no https connection is active and a local universe is bound: SessionStart
creates the row, tool-call events register-on-first-sight + heartbeat,
SessionEnd/Stop delegate the end cleanup, SessionStart reaps stale sessions,
and everything is idempotent + fail-open. The no-universe / prod / https gate
falls back to the current lint-only behavior.
"""

from __future__ import annotations

import json

import pytest

from runtime.harness.hook_runner import local_universe_lifecycle as lul
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client_sessions_helpers import (
    session_offer_db,  # noqa: F401 — re-exported fixture
)


class TestLocalUniverseActiveGate:
    def _cfg(self, monkeypatch, *, https, transport, prod):
        monkeypatch.setattr(
            "yoke_cli.transport.https.resolve_https_connection",
            lambda: object() if https else None,
        )
        monkeypatch.setattr(
            "yoke_cli.config.machine_config.active_connection",
            lambda *a, **k: {"transport": transport},
        )
        monkeypatch.setattr(
            "yoke_contracts.machine_config.schema.connection_is_prod",
            lambda conn: prod,
        )

    def test_local_postgres_non_prod_is_active(self, monkeypatch):
        self._cfg(monkeypatch, https=False, transport="local-postgres", prod=False)
        assert lul.local_universe_active() is True

    def test_https_is_not_active(self, monkeypatch):
        self._cfg(monkeypatch, https=True, transport="local-postgres", prod=False)
        assert lul.local_universe_active() is False

    def test_prod_postgres_is_not_active(self, monkeypatch):
        self._cfg(monkeypatch, https=False, transport="local-postgres", prod=True)
        assert lul.local_universe_active() is False

    def test_non_postgres_transport_is_not_active(self, monkeypatch):
        self._cfg(monkeypatch, https=False, transport="", prod=False)
        assert lul.local_universe_active() is False


@pytest.fixture()
def active_universe(monkeypatch, session_offer_db):  # noqa: F811
    """Pin an active local universe + deterministic identity resolution so the
    orchestrator registers against the fixture DB, project id 1."""
    monkeypatch.setattr(lul, "local_universe_active", lambda: True)
    monkeypatch.setattr(
        lul, "_resolve_project", lambda payload: (1, session_offer_db["tmp_dir"]),
    )
    monkeypatch.setattr(
        "yoke_core.domain.session_process_anchors.record_session_anchor",
        lambda *a, **k: None,
    )
    for name in ("detect_executor", "detect_provider", "detect_entrypoint"):
        monkeypatch.setattr(
            f"runtime.harness.hook_helpers.{name}",
            {"detect_executor": lambda: "claude-code",
             "detect_provider": lambda executor: "anthropic",
             "detect_entrypoint": lambda: "claude-code"}[name],
        )
    monkeypatch.setattr(
        "runtime.harness.hook_helpers.detect_model",
        lambda executor, transcript_path="": TEST_MODEL_ID,
    )
    return session_offer_db


def _row(db, session_id):
    from yoke_core.domain import db_backend

    conn = db_backend.connect()
    try:
        return conn.execute(
            "SELECT ended_at, last_heartbeat FROM harness_sessions "
            "WHERE session_id = %s",
            (session_id,),
        ).fetchone()
    finally:
        conn.close()


class TestRegistration:
    def test_session_start_creates_row(self, active_universe):
        payload = json.dumps({"session_id": "sid-start", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("SessionStart", payload)
        assert _row(active_universe, "sid-start") is not None

    def test_tool_call_registers_on_first_sight(self, active_universe):
        # Tool-call hooks are the only guaranteed event class — they must
        # register a missing session, not just heartbeat.
        payload = json.dumps({"session_id": "sid-tool", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("PreToolUse", payload)
        assert _row(active_universe, "sid-tool") is not None

    def test_registration_is_idempotent_and_convergent(self, active_universe):
        payload = json.dumps({"session_id": "sid-idem", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("SessionStart", payload)
        lul.run_local_universe_session_lifecycle("UserPromptSubmit", payload)
        # A later /yoke do sessions.begin on the same session converges
        # (SESSION_EXISTS -> success), no duplicate row.
        from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
        from yoke_core.domain import db_backend

        conn = db_backend.connect()
        try:
            result = begin_session(
                conn, session_id="sid-idem", executor="claude-code",
                provider="anthropic", model=TEST_MODEL_ID,
                workspace=active_universe["tmp_dir"], project_id=1,
            )
            assert result["success"] is True
            count = conn.execute(
                "SELECT COUNT(*) FROM harness_sessions WHERE session_id = %s",
                ("sid-idem",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 1


class TestHeartbeat:
    def test_heartbeat_updates_registered_session(self, active_universe):
        from yoke_core.domain import db_backend

        payload = json.dumps({"session_id": "sid-hb", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("SessionStart", payload)
        conn = db_backend.connect()
        try:
            conn.execute(
                "UPDATE harness_sessions SET last_heartbeat = %s WHERE session_id = %s",
                ("2000-01-01T00:00:00Z", "sid-hb"),
            )
            conn.commit()
        finally:
            conn.close()
        lul.run_local_universe_session_lifecycle("PostToolUse", payload)
        assert _row(active_universe, "sid-hb")["last_heartbeat"] != "2000-01-01T00:00:00Z"


class TestLifecycleDelegation:
    def test_session_end_delegates_end_cleanup(self, active_universe, monkeypatch):
        calls: list = []
        monkeypatch.setattr(
            "runtime.harness.hook_runner.session_end_cleanup."
            "run_session_end_cleanup_in_process",
            lambda session_id, **kw: calls.append((session_id, kw)),
        )
        payload = json.dumps({"session_id": "sid-end"})
        lul.run_local_universe_session_lifecycle("SessionEnd", payload)
        assert calls and calls[0][0] == "sid-end"
        assert calls[0][1]["event_source"] == "SessionEnd"

    def test_session_start_reaps_stale_sessions(self, active_universe, monkeypatch):
        reaped: list = []
        monkeypatch.setattr(
            "yoke_core.domain.sessions_cleanup.clean_stale_harness_sessions",
            lambda conn, *a, **k: reaped.append(True),
        )
        payload = json.dumps({"session_id": "sid-reap", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("SessionStart", payload)
        assert reaped == [True]


class TestGuardrails:
    def test_no_universe_is_noop(self, monkeypatch, session_offer_db):  # noqa: F811
        monkeypatch.setattr(lul, "local_universe_active", lambda: False)
        payload = json.dumps({"session_id": "sid-none", "model": TEST_MODEL_ID})
        lul.run_local_universe_session_lifecycle("SessionStart", payload)
        assert _row(session_offer_db, "sid-none") is None

    def test_missing_session_id_is_noop(self, active_universe):
        # No session id -> nothing to register; must not raise.
        lul.run_local_universe_session_lifecycle("SessionStart", "{}")

    def test_registration_failure_is_fail_open(self, active_universe, monkeypatch):
        def _boom(*a, **k):
            raise RuntimeError("register exploded")

        monkeypatch.setattr(lul, "_ensure_registered_and_heartbeat", _boom)
        # Must not raise.
        lul.run_local_universe_session_lifecycle(
            "SessionStart", json.dumps({"session_id": "sid-boom"}),
        )
