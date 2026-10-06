"""Tests for explicit session ending through the API."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api.main import app
from runtime.api.sessions_api_test_support import fresh_now
from runtime.api.test_constants import TEST_MODEL_ID
from yoke_core.domain.work_claim_targets import make_item_target

pytest_plugins = ("runtime.api.sessions_api_test_support",)


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
    def setup_client(self, session_test_db):
        self.client = TestClient(app)
        self.client.headers.update(session_test_db["auth_headers"])
        self.db_info = session_test_db

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
               VALUES ({p}, 'claude-code', 'anthropic', '{TEST_MODEL_ID}',
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
               (session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat)
               VALUES ({p}, 'item', {p}, 'exclusive', {p}, {p})""".format(p=p),
            (session_id, make_item_target(10).scope_json(), now, now),
        )
        conn.commit()
        conn.close()

    def test_explicit_end_releases_claim_despite_checkpoint(self):
        """Normal end is blocked while chain work remains."""
        self._insert_chain_pending_session("api-chain-pending")
        resp = self.client.post("/v1/sessions/api-chain-pending/end")

        assert resp.status_code == 200
        assert resp.json()["ended_at"] is not None

        conn = connect_test_db(self.db_info["db_path"])
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = 'api-chain-pending'",
        ).fetchone()
        target = make_item_target(ITEM_ID)
        claim = conn.execute(
            """SELECT released_at FROM work_claims
               WHERE session_id = 'api-chain-pending'
                 AND target_kind = %s AND scope = %s""",
            (target.kind, target.scope_json()),
        ).fetchone()
        conn.close()

        assert row[0] is not None
        assert claim[0] is not None


# ---------------------------------------------------------------------------
# End endpoint behavior
# ---------------------------------------------------------------------------
