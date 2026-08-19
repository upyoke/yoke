"""HTTP /v1/sessions/offer lane-override coverage.

Mirrors the CLI lane-override suite for the FastAPI route: the
session-row ``execution_lane`` is the default. A request-body
``execution_lane`` overrides that default and emits
``SessionOfferLaneOverrideApplied``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_core.domain.scheduler_types import SMLState

import pytest
from fastapi.testclient import TestClient

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import register_session
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api.main import app

pytest_plugins = ("runtime.api.test_session_offer_schemas",)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _set_row_lane(db_path: str, session_id: str, lane: str) -> None:
    conn = connect_test_db(db_path)
    p = _p(conn)
    conn.execute(
        f"UPDATE harness_sessions SET execution_lane = {p} WHERE session_id = {p}",
        (lane, session_id),
    )
    conn.commit()
    conn.close()


def _envelope_lane(db_path: str, session_id: str) -> str | None:
    conn = connect_test_db(db_path)
    p = _p(conn)
    row = conn.execute(
        f"SELECT offer_envelope FROM harness_sessions WHERE session_id = {p}",
        (session_id,),
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0]).get("execution_lane")
    except json.JSONDecodeError:
        return None


def _sml_state_patch(coherent: bool = True):
    """Pin scheduler SML coherence for offer tests (fixture DBs carry no
    strategy_docs table; coherence is read from live strategy_docs rows)."""
    return patch(
        "yoke_core.domain.scheduler._compute_sml_state",
        return_value=SMLState(coherent=coherent),
    )


class TestApiSessionOfferLaneOverride:
    """HTTP route uses the row default unless the body supplies a lane."""

    @pytest.fixture(autouse=True)
    def setup_client(self, session_offer_db):
        self.client = TestClient(app)
        self.client.headers.update(session_offer_db["auth_headers"])
        self.db_info = session_offer_db

    def _ensure_active_session(self, session_id: str, *, lane: str = "DARIUS") -> None:
        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        row = conn.execute(
            "SELECT session_id FROM harness_sessions "
            f"WHERE session_id = {p} AND ended_at IS NULL",
            (session_id,),
        ).fetchone()
        if row is None:
            register_session(
                conn,
                session_id=session_id,
                executor="claude-code",
                provider="anthropic",
                model="claude-opus-4-7",
                workspace="/tmp/api-lane",
                project_id=1,
                execution_lane=lane,
            )
        conn.close()
        _set_row_lane(self.db_info["db_path"], session_id, lane)

    def _post_offer(self, **body) -> dict:
        payload = {
            "session_id": body.pop("session_id"),
            "executor": "claude-code",
            "provider": "anthropic",
            "model": "claude-opus-4-7",
            "workspace": "/tmp/api-lane",
            "execution_lane": body.pop("execution_lane", None),
        }
        payload.update(body)
        with _sml_state_patch():
            resp = self.client.post("/v1/sessions/offer", json=payload)
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_body_primary_against_darius_row_uses_caller_lane(self):
        sid = "http-lane-anchor-applied"
        self._ensure_active_session(sid, lane="DARIUS")
        self._post_offer(session_id=sid, execution_lane="primary")
        assert _envelope_lane(self.db_info["db_path"], sid) == "primary"

    def test_matching_body_lane_persists_row_lane(self):
        sid = "http-lane-anchor-match"
        self._ensure_active_session(sid, lane="DARIUS")
        self._post_offer(session_id=sid, execution_lane="DARIUS")
        assert _envelope_lane(self.db_info["db_path"], sid) == "DARIUS"

    def test_omitted_body_lane_persists_row_lane(self):
        sid = "http-lane-anchor-omitted"
        self._ensure_active_session(sid, lane="DARIUS")
        self._post_offer(session_id=sid, execution_lane=None)
        assert _envelope_lane(self.db_info["db_path"], sid) == "DARIUS"

    def test_default_sentinel_persists_row_lane(self):
        sid = "http-lane-anchor-default"
        self._ensure_active_session(sid, lane="DARIUS")
        self._post_offer(session_id=sid, execution_lane="default")
        assert _envelope_lane(self.db_info["db_path"], sid) == "DARIUS"
