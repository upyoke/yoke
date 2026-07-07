"""Charge-flow tests for service_client session-offer command.

Covers: charge action with runnable items, drift-review failure escalation,
frontier-only checkpoint suppression, scheduler next-step, and full event
trace persistence.

Basic offer + lane resolution → test_service_client_sessions_offer.py
Resume + stale recovery → test_service_client_sessions_offer_resume.py
Persistence + concurrency → test_service_client_sessions_offer_persist.py
"""

from __future__ import annotations

import json
import os

import pytest  # noqa: F401  (used by monkeypatch / capsys fixtures)

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_constants import TEST_MODEL_ID


class TestSessionOfferCharge:
    """Tests for service_client.py session-offer charge flow."""

    def test_session_offer_charge_with_runnable(self, session_offer_db):
        """With runnable items and SML present, should return charge."""
        # Create SML files so sml_coherent=True
        ws = session_offer_db["tmp_dir"]
        strategy_dir = os.path.join(ws, "strategy")
        os.makedirs(strategy_dir, exist_ok=True)
        with open(os.path.join(strategy_dir, "VISION.md"), "w") as f:
            f.write("# Vision\n")
        with open(os.path.join(strategy_dir, "MASTER-PLAN.md"), "w") as f:
            f.write("# Master Plan\n")

        sid = "charge-runnable-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=ws)
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", ws,
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["action"] == "charge"
        assert data["chainable"] is True

    def test_cmd_session_offer_drift_review_failure_returns_escalate(self, session_offer_db, monkeypatch, capsys):
        """CLI surfaces drift-review failures as escalate JSON."""
        import yoke_core.api.service_client as service_client

        def _raise(*_args, **_kwargs):
            raise RuntimeError("boom")

        sid = "drift-review-fail-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        monkeypatch.setenv("YOKE_DB", session_offer_db["db_path"])
        monkeypatch.setattr(service_client, "assess_post_delivery_drift", _raise)

        rc = service_client.cmd_session_offer([
            "--executor", "DARIUS",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["action"] == "escalate"
        assert data["context"]["trigger"] == "drift_review"
        assert "boom" in data["context"]["error"]

    def test_cmd_session_offer_frontier_only_charge_does_not_emit_checkpoint(self, session_offer_db, monkeypatch, capsys):
        """charge-winning frontier reviews must stay uncheckpointed."""
        import yoke_core.api.service_client as service_client
        from yoke_core.domain.drift_review import DriftReviewResult

        emitted: list[dict] = []

        def _record_emit(**kwargs):
            emitted.append(kwargs)

        sid = "frontier-only-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        monkeypatch.setenv("YOKE_DB", session_offer_db["db_path"])
        monkeypatch.setattr(
            service_client,
            "assess_post_delivery_drift",
            lambda *_args, **_kwargs: DriftReviewResult(
                classification="frontier_only",
                summary="frontier changed",
                checkpoint_start="2026-04-01T00:00:00Z",
                reviewed_through="2026-04-02T00:00:00Z",
                delivered_items=["YOK-999"],
            ),
        )
        monkeypatch.setattr(service_client, "emit_drift_review_completed", _record_emit)

        rc = service_client.cmd_session_offer([
            "--executor", "DARIUS",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0
        assert data["action"] == "charge"
        assert emitted == []

    def test_session_offer_charge_includes_scheduler_next_step(self, session_offer_db):
        """Charge responses expose the scheduler's routing decision."""
        sid = "charge-next-step-session"
        _pre_register_session(session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "charge"
        scheduler = data["context"]["scheduler"]
        assert scheduler["next_step"] == "advance"
        assert scheduler["status"] == "refined-idea"
        assert scheduler["adapter"] == "conduct"

    def _now_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _seed_claim(
        self,
        db_path: str,
        *,
        item_id: int,
        status: str,
        owner_session: str,
        register_owner: bool = True,
        seed_item: bool = True,
    ) -> str:
        now = self._now_iso()
        conn = connect_test_db(db_path)
        try:
            if seed_item:
                conn.execute(
                    """INSERT INTO items
                       (id, title, type, status, priority, project_id, project_sequence,
                        created_at, updated_at, source, frozen)
                       VALUES (%s, %s, 'issue', %s, 'medium', 1, %s,
                               %s, %s, 'user', 0)""",
                    (item_id, f"Resumable {item_id}", status, item_id, now, now),
                )
            if register_owner:
                conn.execute(
                    f"""INSERT INTO harness_sessions
                       (session_id, executor, provider, model, workspace,
                        offered_at, last_heartbeat)
                       VALUES (%s, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}',
                               '/tmp', %s, %s)""",
                    (owner_session, now, now),
                )
            conn.execute(
                """INSERT INTO work_claims
                   (session_id, target_kind, item_id, claim_type,
                    claimed_at, last_heartbeat)
                   VALUES (%s, 'item', %s, 'exclusive', %s, %s)""",
                (owner_session, item_id, now, now),
            )
            conn.commit()
        finally:
            conn.close()
        return f"YOK-{item_id}"

    def _offer(self, session_offer_db, sid: str) -> dict:
        _pre_register_session(
            session_offer_db["db_path"], sid, workspace=session_offer_db["tmp_dir"]
        )
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        return json.loads(result.stdout)

    @pytest.mark.parametrize(
        "item_id,status,sid",
        [
            (20, "implementing", "charge-other-live-implementing"),
            (21, "reviewing-implementation", "charge-other-live-reviewing"),
        ],
    )
    def test_session_offer_excludes_other_live_claimed(
        self, session_offer_db, item_id, status, sid
    ):
        """AC-1/5/6: other-live resumable work is not assignable."""
        held = self._seed_claim(
            session_offer_db["db_path"],
            item_id=item_id,
            status=status,
            owner_session=f"other-live-{item_id}",
        )
        data = self._offer(session_offer_db, sid)
        ctx = data.get("context", {})
        assert held not in ctx.get("runnable_items", [])
        assert ctx.get("selected_item") != held

    def test_projection_keeps_self_and_stale_runnable_drops_other_live(self):
        """AC-3/7: projection keeps assignable states only."""
        from yoke_core.domain.scheduler_types import (
            ClaimState,
            NextStep,
            ScheduledStep,
            SchedulerResult,
            SMLState,
        )
        from yoke_core.api.service_client_sessions_frontier import (
            build_frontier_state_from_schedule,
        )

        steps = [
            ScheduledStep(
                item_id=item_id,
                item_type="issue",
                status="implementing",
                title=item_id,
                priority="medium",
                next_step=NextStep.ADVANCE,
                rank=rank,
                claim_state=cs,
            )
            for rank, (item_id, cs) in enumerate(
                [
                    ("YOK-A", ClaimState.UNCLAIMED),
                    ("YOK-B", ClaimState.CLAIMED_BY_SELF),
                    ("YOK-C", ClaimState.CLAIMED_BY_STALE),
                    ("YOK-D", ClaimState.CLAIMED_BY_OTHER_LIVE),
                ]
            )
        ]
        schedule = SchedulerResult(
            project_scope=["yoke"],
            sml_state=SMLState(coherent=True),
            ranked_steps=steps,
        )
        state = build_frontier_state_from_schedule(schedule)
        assert state.runnable_items == ["YOK-A", "YOK-B", "YOK-C"]
        assert "YOK-D" not in state.runnable_items

    def test_session_offer_empty_runnable_when_all_other_live_claimed(
        self, session_offer_db
    ):
        """AC-9/12/13: all other-live work yields no charge dispatch."""
        self._seed_claim(
            session_offer_db["db_path"],
            item_id=10,
            status="refined-idea",
            owner_session="all-other-live-owner",
            seed_item=False,
        )
        data = self._offer(session_offer_db, "charge-no-assignable")
        ctx = data.get("context", {})
        assert ctx.get("runnable_items", []) == []
        assert ctx.get("selected_item") in (None, "")
        assert data["action"] != "charge"

    def test_session_offer_persists_full_trace_with_session_scoped_events(self, session_offer_db):
        """The charge decision chain is queryable by session_id end-to-end."""
        session_id = "trace-sess"
        _pre_register_session(session_offer_db["db_path"], session_id, workspace=session_offer_db["tmp_dir"])
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", session_id,
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        conn = connect_test_db(session_offer_db["db_path"])
        rows = conn.execute(
            "SELECT event_name, envelope FROM events WHERE session_id = %s ORDER BY created_at",
            (session_id,),
        ).fetchall()
        conn.close()

        event_names = [row[0] for row in rows]
        assert "HarnessSessionOffered" in event_names
        assert "FrontierComputed" in event_names
        assert "DependencyGateEvaluated" in event_names
        assert "FrontierStepSelected" in event_names
        assert "LaneRoutingDecision" in event_names
        assert "AdapterDispatchChosen" in event_names
        assert "NextActionChosen" in event_names

        dispatch_event = next(
            json.loads(row[1]) for row in rows if row[0] == "AdapterDispatchChosen"
        )
        assert dispatch_event["context"]["adapter"] == "advance"
        assert dispatch_event["context"]["dispatch_source"] == "scheduler.next_step"
