"""Session offer endpoint tests — decision/edge cases.

Lane-routing + eager-claim-release tests live in
``test_api_sessions_lanes.py``; resume-flow tests live in
``test_api_sessions_resume.py``; the session-end endpoint and service-client
offer tests live in ``test_api_sessions_end.py``. Shared schema/fixture
helpers live in ``test_session_offer_schemas.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from yoke_core.domain import db_backend
from yoke_core.domain.sessions import register_session
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api.main import app
from runtime.api.test_session_offer_schemas import session_offer_db  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestSessionOffer:
    """Tests for POST /v1/sessions/offer — decision + lane behavior."""

    @pytest.fixture(autouse=True)
    def setup_client(self, session_offer_db):
        self.client = TestClient(app)
        self.client.headers.update(session_offer_db["auth_headers"])
        self.db_info = session_offer_db

    def _make_offer(self, **overrides):
        payload = {
            "session_id": "test-session-001",
            "executor": "DARIUS",
            "provider": "anthropic",
            "model": TEST_MODEL_ID,
            "workspace": "/tmp/test-workspace",
            "execution_lane": "DARIUS",
        }
        payload.update(overrides)
        return payload

    def _ensure_active_session(
        self,
        session_id: str,
        *,
        executor: str = "DARIUS",
        provider: str = "anthropic",
        model: str = TEST_MODEL_ID,
        workspace: str = "/tmp/test-workspace",
        execution_lane: str = "DARIUS",
    ) -> None:
        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        row = conn.execute(
            f"SELECT session_id FROM harness_sessions WHERE session_id = {p} AND ended_at IS NULL",
            (session_id,),
        ).fetchone()
        if row is None:
            register_session(
                conn,
                session_id=session_id,
                executor=executor,
                provider=provider,
                model=model,
                workspace=workspace,
                project_id=1,
                execution_lane=execution_lane,
            )
        conn.close()

    def test_offer_returns_next_action(self):
        """AC-1: POST /v1/sessions/offer returns a NextAction JSON."""
        self._ensure_active_session("test-session-001")
        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert "action" in data
        assert "reason" in data
        assert "correlation_id" in data
        assert data["correlation_id"] == "test-session-001"

    def test_offer_charge_with_runnable_items(self):
        """AC-4: Session-offer exposes routed issue scheduling truth."""
        self._ensure_active_session("test-session-001")
        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.release_item_claim_for_execution") as mock_release:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        # is runnable, child is blocked by parent
        assert data["action"] == "charge"
        ctx = data.get("context", {})
        assert "selected_item" in ctx
        assert ctx["selected_item"] == "YOK-10"
        assert "runnable_items" in ctx
        assert "YOK-10" in ctx["runnable_items"]
        assert ctx["scheduler"]["next_step"] == "advance"
        assert ctx["scheduler"]["status"] == "refined-idea"
        # The scheduler carries the raw frontier adapter for diagnostics,
        # but session-offer dispatches from next_step.
        assert ctx["scheduler"]["adapter"] == "conduct"
        # should NOT be in runnable (blocked by parent (activation gate))
        assert "YOK-12" not in ctx["runnable_items"]

        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        active_claims = conn.execute(
            f"SELECT item_id FROM work_claims WHERE session_id = {p} AND released_at IS NULL",
            ("test-session-001",),
        ).fetchall()
        conn.close()
        assert len(active_claims) == 1
        assert active_claims[0]["item_id"] == 10
        mock_release.assert_not_called()

    def test_offer_runnable_items_excludes_other_live_claimed(self):
        """AC-3, AC-5: the FastAPI projection mirrors the CLI assignability rule —
        ranked steps held by another live session are filtered out of
        ``runnable_items`` and the offering session never picks one."""
        from datetime import datetime, timezone

        self._ensure_active_session("test-session-001")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        owner = "other-live-owner-fastapi"
        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        try:
            conn.execute(
                """INSERT INTO items
                   (id, title, type, status, priority, project_id, project_sequence,
                    created_at, updated_at, source, frozen)
                   VALUES (30, 'Live-claimed implementing', 'issue',
                           'implementing', 'medium', 1, 30,
                           {p}, {p}, 'user', 0)""".format(p=p),
                (now_iso, now_iso),
            )
            conn.execute(
                f"""INSERT INTO harness_sessions
                   (session_id, executor, provider, model, workspace, project_id,
                    offered_at, last_heartbeat)
                   VALUES ({p}, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}',
                           '/tmp', 1, {p}, {p})""",
                (owner, now_iso, now_iso),
            )
            conn.execute(
                """INSERT INTO work_claims
                   (session_id, target_kind, item_id, claim_type,
                    claimed_at, last_heartbeat)
                   VALUES ({p}, 'item', 30, 'exclusive', {p}, {p})""".format(p=p),
                (owner, now_iso, now_iso),
            )
            conn.commit()
        finally:
            conn.close()

        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.release_item_claim_for_execution"):
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        ctx = data.get("context", {})
        runnable = ctx.get("runnable_items", [])
        assert "YOK-30" not in runnable
        assert ctx.get("selected_item") != "YOK-30"

    def test_offer_drift_review_failure_returns_escalate(self):
        """drift-review failures surface escalate instead of 500."""
        self._ensure_active_session("test-session-001")
        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.assess_post_delivery_drift", side_effect=RuntimeError("boom")):
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "escalate"
        assert data["context"]["trigger"] == "drift_review"
        assert "boom" in data["context"]["error"]

    def test_offer_frontier_only_charge_does_not_emit_checkpoint(self):
        """frontier_only review must not checkpoint when charge still wins."""
        self._ensure_active_session("test-session-001")
        from yoke_core.domain.drift_review import DriftReviewResult

        drift = DriftReviewResult(
            classification="frontier_only",
            summary="frontier changed",
            checkpoint_start="2026-04-01T00:00:00Z",
            reviewed_through="2026-04-02T00:00:00Z",
            delivered_items=["YOK-999"],
        )

        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.assess_post_delivery_drift", return_value=drift), \
             patch("yoke_core.api.main.emit_drift_review_completed") as mock_emit:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        assert resp.json()["action"] == "charge"
        mock_emit.assert_not_called()

    def test_offer_returns_400_missing_fields(self):
        """AC-2: Missing required fields return 400."""
        # Missing executor
        resp = self.client.post("/v1/sessions/offer", json={
            "session_id": "test",
            "provider": "anthropic",
            "model": "test-model",
            "workspace": "/tmp/test",
        })
        assert resp.status_code == 422  # Pydantic validation

    def test_offer_strategize_without_sml_charges_available_work(self):
        """DB process policy skips strategize and charges available work."""
        self._ensure_active_session("test-session-001")
        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = False
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "charge"
        assert data["context"]["selected_item"] == "YOK-10"
        suppressed = data["context"]["skipped_process"]
        assert suppressed["process_key"] == "STRATEGIZE"

    def test_offer_escalate_all_blocked(self):
        """When all items are blocked and SML is coherent, returns escalate."""
        self._ensure_active_session("test-session-001")
        # Make parent blocked too (add dependency on a non-terminal item)
        conn = connect_test_db(self.db_info["db_path"])
        # Freeze parent so it's not runnable, add a new non-frozen blocked item
        conn.execute("UPDATE items SET frozen = 1 WHERE id = 10")
        conn.commit()
        conn.close()

        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        # is blocked by parent (activation blocker), parent is frozen.
        # Only child remains, and it's blocked -> escalate
        assert data["action"] == "escalate"
        assert "blocked_items" in data.get("context", {})
        assert "YOK-12" in data["context"]["blocked_items"]

    def test_offer_feed_empty_frontier(self):
        """DB process policy suppresses feed when the frontier is empty."""
        self._ensure_active_session("test-session-001")
        conn = connect_test_db(self.db_info["db_path"])
        conn.execute("UPDATE items SET status = 'done'")
        conn.commit()
        conn.close()

        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "wait"
        assert data["context"]["wait_reason"] == "process_suppressed_no_alternative"
        suppressed = data["context"]["suppressed_process_recommendation"]
        assert suppressed["process_key"] == "FEED"

    def test_offer_response_includes_chainable(self):
        """Response JSON always includes the chainable field."""
        self._ensure_active_session("test-session-001")
        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert "chainable" in data

    def test_offer_empty_string_fields_returns_400(self):
        """Empty string for required fields returns 400."""
        resp = self.client.post("/v1/sessions/offer", json={
            "session_id": "",
            "executor": "DARIUS",
            "provider": "anthropic",
            "model": TEST_MODEL_ID,
            "workspace": "/tmp/test",
        })
        assert resp.status_code == 400
