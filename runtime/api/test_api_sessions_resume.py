"""Session offer resume-flow tests for POST /v1/sessions/offer.

Decision/lane behavior tests live in ``test_api_sessions.py``; the session-end
endpoint and service-client offer tests live in ``test_api_sessions_end.py``.
Shared schema/fixture helpers live in ``test_session_offer_schemas.py``.
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
from runtime.api.test_session_offer_schemas import fresh_now, session_offer_db  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _sml_state_patch(coherent: bool = True):
    """Pin scheduler SML coherence for offer tests (fixture DBs carry no
    strategy_docs table; coherence is read from live strategy_docs rows)."""
    return patch(
        "yoke_core.domain.scheduler._compute_sml_state",
        return_value=SMLState(coherent=coherent),
    )


class TestSessionOfferResume:
    """Resume-flow paths for POST /v1/sessions/offer."""

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

    def test_offer_resume_with_active_claim(self):
        """When session has active claims, decision engine returns resume."""
        # Add an active claim for the session
        conn = connect_test_db(self.db_info["db_path"])
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offered_at, last_heartbeat)
               VALUES ('test-session-001', 'DARIUS', 'anthropic',
                       '{TEST_MODEL_ID}', '/tmp/test', 1, {p}, {p})""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('test-session-001', 'item', 10, 'exclusive', {p}, {p})""".format(p=p),
            (now, now),
        )
        conn.commit()
        conn.close()

        with _sml_state_patch():
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "resume"
        assert data["context"]["item_id"] == "YOK-10"

    def test_offer_resume_with_epic_task_claim(self):
        """AC-9: historical epic task claim rows still surface in resume context."""
        conn = connect_test_db(self.db_info["db_path"])
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offered_at, last_heartbeat)
               VALUES ('test-session-001', 'DARIUS', 'anthropic',
                       '{TEST_MODEL_ID}', '/tmp/test', 1, {p}, {p})""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, epic_id, task_num, claim_type, claimed_at, last_heartbeat)
               VALUES ('test-session-001', 'epic_task', 100, 3, 'exclusive', {p}, {p})""".format(p=p),
            (now, now),
        )
        conn.commit()
        conn.close()

        with _sml_state_patch():
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "resume"
        assert data["context"]["epic_id"] == 100
        assert data["context"]["task_num"] == 3

    def test_offer_resume_enforces_supported_paths(self):
        """API resume derives required_path from current item state."""
        conn = connect_test_db(self.db_info["db_path"])
        conn.execute("UPDATE items SET status = 'reviewed-implementation' WHERE id = 10")
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offer_envelope, offered_at, last_heartbeat)
               VALUES ('test-session-001', 'DARIUS', 'anthropic',
                       '{TEST_MODEL_ID}', '/tmp/test', 1, '{{}}', {p}, {p})""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('test-session-001', 'item', 10, 'exclusive', {p}, {p})""".format(p=p),
            (now, now),
        )
        conn.commit()
        conn.close()

        with _sml_state_patch():
            resp = self.client.post(
                "/v1/sessions/offer",
                json=self._make_offer(supported_paths=["advance"]),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "escalate"
        assert data["context"]["escalate_reason"] == "unsupported_path"
        assert data["context"]["required_path"] == "polish"

    def test_offer_resume_no_progress_escalates(self):
        """API re-offer hits the bounded-resume escalate when prior checkpoint
        was a completed resume on the same item/required_path with no progress.

        Documented at docs/session-offer-contract/action-payloads.md (bounded
        resume): a prior ``handler_outcome='completed'`` resume checkpoint on
        the same work + same status/required_path causes the next offer to
        return ``escalate`` with ``escalate_reason='resume_no_progress'`` rather
        than burn another chain step on a no-progress loop.
        """
        checkpoint = {
            "step": 1,
            "action": "resume",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": "YOK-10",
            "status": "reviewed-implementation",
            "required_path": "polish",
        }
        conn = connect_test_db(self.db_info["db_path"])
        conn.execute("UPDATE items SET status = 'reviewed-implementation' WHERE id = 10")
        now = fresh_now()
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offer_envelope, offered_at, last_heartbeat)
               VALUES ({p}, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}',
                       '/tmp/test', 1, {p}, {p}, {p})""",
            (
                "test-session-001",
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
                now,
                now,
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('test-session-001', 'item', 10, 'exclusive', {p}, {p})""".format(p=p),
            (now, now),
        )
        conn.commit()
        conn.close()

        with _sml_state_patch():
            resp = self.client.post(
                "/v1/sessions/offer",
                json=self._make_offer(step=2, supported_paths=["polish"]),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "escalate"
        assert data["context"]["escalate_reason"] == "resume_no_progress"
        assert data["context"]["required_path"] == "polish"

    def test_offer_no_runnable_items_when_claim_filter_leaves_no_assignable_work(self):
        """Claim-filtered empty frontiers fall through to no_runnable_items feed.

        Drops the dependent → blocker dependency that the shared fixture
        seeds, then live-claims the blocker from another session. With the
        projection-layer claim filter, the blocker leaves ``runnable_items``
        and the dependent (no longer blocked but still ``idea`` status) is
        also off the runnable frontier — leaving nothing assignable, so the
        decision engine routes through the ``no_runnable_items`` feed branch.
        """
        self._ensure_active_session("test-session-001")
        conn = connect_test_db(self.db_info["db_path"])
        now = fresh_now()
        # The shared fixture seeds the dependent (idea) blocked by the
        # blocker (refined-idea). Drop the dep edge AND freeze the dependent
        # so the blocker is the only frontier row — once the projection-layer
        # claim filter removes it, runnable is empty and the decision engine
        # takes the no_runnable_items branch. Without these adjustments the
        # leftover state would either route via escalate (dependent still
        # blocked) or via charge on the dependent (idea → refine).
        conn.execute("DELETE FROM item_dependencies WHERE dependent_item='YOK-12'")
        conn.execute("UPDATE items SET frozen=1 WHERE id=12")
        p = _p(conn)
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, project_id,
                offered_at, last_heartbeat)
               VALUES ('other-session', 'ALTMAN', 'anthropic',
                       '{TEST_MODEL_ID}', '/tmp/test', 1, {p}, {p})""",
            (now, now),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('other-session', 'item', 10, 'exclusive', {p}, {p})""".format(p=p),
            (now, now),
        )
        conn.commit()
        conn.close()

        with _sml_state_patch():
            resp = self.client.post("/v1/sessions/offer", json=self._make_offer())

        assert resp.status_code == 200
        data = resp.json()
        ctx = data.get("context", {})
        # The live-claimed blocker must never reach the offering session as
        # runnable, regardless of which empty-frontier branch the decision
        # engine picks.
        assert "YOK-10" not in ctx.get("runnable_items", [])
        assert ctx.get("selected_item") != "YOK-10"
        assert data["action"] in ("feed", "wait")
        if data["action"] == "feed":
            assert ctx["trigger"] == "no_runnable_items"
