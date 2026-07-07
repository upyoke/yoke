"""Lane-routing and eager-claim-release tests for POST /v1/sessions/offer."""

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


class TestSessionOfferLanes:
    """Lane-routing + eager-claim-release behavior for POST /v1/sessions/offer."""

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

    def test_offer_strategize_releases_eager_claim_before_next_action(self):
        """API adapter also reconciles eager claims on non-charge decisions."""
        import yoke_core.api.main as api_main
        from yoke_core.domain.session import ActionKind, NextAction

        session_id = "api-offer-override-sess"
        self._ensure_active_session(session_id)
        call_order = []

        real_release = api_main.release_item_claim_for_execution

        def _force_strategize(offer, frontier, claims, **kwargs):
            return NextAction(
                action=ActionKind.STRATEGIZE,
                reason="Drift review: both SML and frontier impacted.",
                chainable=False,
                correlation_id=offer.session_id,
                context={"trigger": "drift_review"},
            )

        def _record_release(*args, **kwargs):
            call_order.append("release")
            return real_release(*args, **kwargs)

        def _record_next_action(*args, **kwargs):
            call_order.append("next_action")
            return None

        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.decide_next_action", side_effect=_force_strategize), \
             patch("yoke_core.api.main.release_item_claim_for_execution", side_effect=_record_release), \
             patch("yoke_core.api.main.emit_next_action_chosen", side_effect=_record_next_action):
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post(
                "/v1/sessions/offer",
                json=self._make_offer(session_id=session_id),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "strategize"

        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        active_claims = conn.execute(
            f"SELECT * FROM work_claims WHERE session_id = {p} AND released_at IS NULL",
            (session_id,),
        ).fetchall()
        conn.close()

        assert active_claims == []
        assert call_order == ["release", "next_action"]

    def test_offer_uses_existing_session_lane(self):
        """Offer preserves the lane recorded on the active session."""
        self._ensure_active_session(
            "test-session-config-lane",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json={
                "session_id": "test-session-config-lane",
                "executor": "codex",
                "provider": "openai",
                "model": "gpt-5.4",
                "workspace": "/tmp/test-workspace",
            })

        assert resp.status_code == 200

        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        row = conn.execute(
            f"SELECT execution_lane FROM harness_sessions WHERE session_id = {p}",
            ("test-session-config-lane",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "ALTMAN"

    def test_offer_default_lane_alias_uses_registered_lane(self):
        """Offer keeps the lane on a pre-registered session."""
        self._ensure_active_session(
            "test-session-default-alias",
            executor="claude-code",
            execution_lane="DARIUS",
        )
        with patch("yoke_core.domain.scheduler.Path") as mock_path:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json={
                "session_id": "test-session-default-alias",
                "executor": "claude-code",
                "provider": "anthropic",
                "model": TEST_MODEL_ID,
                "workspace": "/tmp/test-workspace",
                "execution_lane": "default",
            })

        assert resp.status_code == 200

        conn = connect_test_db(self.db_info["db_path"])
        p = _p(conn)
        row = conn.execute(
            f"SELECT execution_lane FROM harness_sessions WHERE session_id = {p}",
            ("test-session-default-alias",),
        ).fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "DARIUS"

    def test_offer_lane_telemetry_uses_resolved_lane(self):
        """Lane-routing telemetry should record the resolved executor-default lane."""
        self._ensure_active_session(
            "test-session-telemetry-lane",
            executor="codex",
            provider="openai",
            model="gpt-5.4",
            execution_lane="ALTMAN",
        )
        with patch("yoke_core.domain.scheduler.Path") as mock_path, \
             patch("yoke_core.api.main.emit_post_decision_telemetry") as mock_emit:
            mock_file = MagicMock()
            mock_file.is_file.return_value = True
            mock_file.stat.return_value = MagicMock(st_mtime=9999999999.0)
            mock_path.return_value.__truediv__ = lambda self, name: mock_file
            resp = self.client.post("/v1/sessions/offer", json={
                "session_id": "test-session-telemetry-lane",
                "executor": "codex",
                "provider": "openai",
                "model": "gpt-5.4",
                "workspace": "/tmp/test-workspace",
                "execution_lane": "ALTMAN",
            })

        assert resp.status_code == 200
        mock_emit.assert_called_once()
        assert mock_emit.call_args.kwargs["actual_lane"] == "ALTMAN"
