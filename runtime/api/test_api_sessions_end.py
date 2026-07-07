"""Session-end endpoint and service-client session-offer tests.

Decision/lane behavior tests live in ``test_api_sessions.py``; resume-flow
tests live in ``test_api_sessions_resume.py``. Shared schema/fixture
helpers live in ``test_session_offer_schemas.py``.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.sessions import register_session
from yoke_core.api.main import app
from runtime.api.test_session_offer_schemas import fresh_now, session_offer_db  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client import (
    _REPO_ROOT,
    _service_client_cmd,
    _with_source_pythonpath,
)


ITEM_ID = 10
ITEM_REF = f"YOK-{ITEM_ID}"


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Session end endpoint tests
# ---------------------------------------------------------------------------


class TestSessionEndEndpoint:
    """Tests for POST /v1/sessions/{session_id}/end."""

    @pytest.fixture(autouse=True)
    def setup_client(self, session_offer_db):
        self.client = TestClient(app)
        self.client.headers.update(session_offer_db["auth_headers"])
        self.db_info = session_offer_db

    def _insert_chain_pending_session(self, session_id: str) -> None:
        checkpoint = {
            "step": 1,
            "action": "resume",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": ITEM_REF,
            "status": "reviewed-implementation",
            "required_path": "polish",
        }
        conn = connect_test_db(self.db_info["db_path"])
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offer_envelope, offered_at, last_heartbeat)
               VALUES ({p}, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}',
                       '/tmp/test', 1, {p}, {p}, {p})""",
            (
                session_id,
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ({p}, 'item', 10, 'exclusive', {p}, {p})""".format(p=p),
            (session_id, now, now),
        )
        conn.commit()
        conn.close()

    def test_end_session_chain_pending_returns_409(self):
        """AC-1: normal end is blocked while chain work remains."""
        self._insert_chain_pending_session("api-chain-pending")
        resp = self.client.post("/v1/sessions/api-chain-pending/end")

        assert resp.status_code == 409
        data = resp.json()
        assert data["error"]["code"] == "CHAIN_PENDING"

        conn = connect_test_db(self.db_info["db_path"])
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'api-chain-pending'",
        ).fetchone()
        claim = conn.execute(
            """SELECT released_at FROM work_claims
               WHERE session_id = 'api-chain-pending'
                 AND target_kind='item' AND item_id = 10""",
        ).fetchone()
        conn.close()

        assert row[0] is None
        assert claim[0] is None

    def test_end_session_force_alone_still_returns_chain_pending(self):
        """AC-9 / AC-13: ``force`` alone no longer bypasses CHAIN_PENDING on the API path."""
        self._insert_chain_pending_session("api-chain-force")
        resp = self.client.post("/v1/sessions/api-chain-force/end?force=true")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "CHAIN_PENDING"

    def test_end_session_override_without_rationale_returns_400(self):
        """AC-9 / AC-13: API rejects override flag with empty rationale."""
        self._insert_chain_pending_session("api-empty-rationale")
        resp = self.client.post(
            "/v1/sessions/api-empty-rationale/end",
            params={"override_chain_end": True, "chain_end_rationale": "   "},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "OVERRIDE_RATIONALE_REQUIRED"

    def test_end_session_override_with_rationale_no_claims_succeeds(self):
        """AC-9 / AC-13: override + rationale ends the session via the API path."""
        checkpoint = {
            "step": 1, "action": "resume", "chainable": True,
            "handler_outcome": "completed",
        }
        conn = connect_test_db(self.db_info["db_path"])
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offer_envelope, offered_at, last_heartbeat)
               VALUES ({p}, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}',
                       '/tmp/test', 1, {p}, {p}, {p})""",
            (
                "api-override-noclaim",
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
        resp = self.client.post(
            "/v1/sessions/api-override-noclaim/end",
            params={
                "override_chain_end": True,
                "chain_end_rationale": "operator override — harness restart",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ended_at"] is not None


# ---------------------------------------------------------------------------
# Service client session-offer tests
# ---------------------------------------------------------------------------


class TestServiceClientSessionOffer:
    """Tests for service_client.py session-offer command."""

    def test_session_offer_prints_json(self, session_offer_db):
        """AC-3: session-offer prints NextAction JSON to stdout."""
        import subprocess

        env = os.environ.copy()
        env["YOKE_DB"] = session_offer_db["db_path"]
        conn = connect_test_db(session_offer_db["db_path"])
        register_session(
            conn,
            session_id="DARIUS-test-session",
            executor="DARIUS",
            provider="anthropic",
            model=TEST_MODEL_ID,
            workspace=session_offer_db["tmp_dir"],
            project_id=1,
            execution_lane="primary",
        )
        conn.close()

        result = subprocess.run(
            _service_client_cmd([
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "DARIUS-test-session",
            ]),
            env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert "action" in data
        assert "reason" in data
        assert "correlation_id" in data

    def test_session_offer_missing_args_exits_2(self, session_offer_db):
        """Missing required args should exit with code 2."""
        import subprocess

        env = os.environ.copy()
        env["YOKE_DB"] = session_offer_db["db_path"]

        result = subprocess.run(
            _service_client_cmd([
                "session-offer",
                "--executor", "DARIUS",
                # Missing --provider, --model, --workspace
            ]),
            env=_with_source_pythonpath(env),
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
        )

        assert result.returncode == 2
