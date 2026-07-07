"""Resume + stale-claim recovery tests for service_client session-offer.

Basic offer + lane resolution → test_service_client_sessions_offer.py
Charge flow → test_service_client_sessions_offer_charge.py
Persistence + concurrency → test_service_client_sessions_offer_persist.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)
from runtime.api.test_constants import TEST_MODEL_ID


class TestSessionOfferResume:
    """CLI session-offer resume and stale-claim recovery flows."""

    def test_session_offer_recovers_stale_claimed_work(self, session_offer_db):
        """AC-3/AC-7: CLI session-offer recovers stale-claimed work."""
        conn = connect_test_db(session_offer_db["db_path"])
        stale_iso = "2000-01-01T00:00:00Z"
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('stale-offer', 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', '/tmp/test', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('stale-offer', 'item', 10, 'exclusive', %s, %s)""",
            (stale_iso, stale_iso),
        )
        conn.commit()
        conn.close()

        sid = "rescuer-sess"
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
        assert data["context"]["selected_item"] == "YOK-10"

        conn = connect_test_db(session_offer_db["db_path"])
        stale_claim = conn.execute(
            """SELECT released_at, release_reason FROM work_claims
               WHERE session_id = 'stale-offer' AND target_kind='item' AND item_id = 10"""
        ).fetchone()
        new_claim = conn.execute(
            """SELECT item_id FROM work_claims
               WHERE session_id = 'rescuer-sess' AND released_at IS NULL"""
        ).fetchone()
        conn.close()

        assert stale_claim["released_at"] is not None
        assert stale_claim["release_reason"] == "reclaimed"
        assert new_claim is not None
        assert new_claim["item_id"] == 10

    def test_session_offer_resume_with_epic_task_claim(self, session_offer_db):
        """AC-9: historical epic task claim rows still surface in resume context."""
        conn = connect_test_db(session_offer_db["db_path"])
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat)
               VALUES ('sess-epic-task', 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', '/tmp/test', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, epic_id, task_num, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-epic-task', 'epic_task', 100, 3, 'exclusive', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "sess-epic-task",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "resume"
        assert data["context"]["epic_id"] == 100
        assert data["context"]["task_num"] == 3

    def test_session_offer_resume_enforces_supported_paths(self, session_offer_db):
        """CLI resume derives required_path from current item state."""
        conn = connect_test_db(session_offer_db["db_path"])
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE items SET status = 'reviewed-implementation' WHERE id = 10")
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat, offer_envelope)
               VALUES ('sess-resume-path', 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', '/tmp/test', %s, %s, '{{}}')""",
            (fresh_iso, fresh_iso),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-resume-path', 'item', 10, 'exclusive', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "sess-resume-path",
                "--supported-paths", "advance",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "escalate"
        assert data["context"]["escalate_reason"] == "unsupported_path"
        assert data["context"]["required_path"] == "polish"

    def test_session_offer_resume_no_progress_escalates(self, session_offer_db):
        """CLI re-offer hits the bounded-resume escalate when prior checkpoint
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
        conn = connect_test_db(session_offer_db["db_path"])
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE items SET status = 'reviewed-implementation' WHERE id = 10")
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat, offer_envelope)
               VALUES (%s, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', '/tmp/test', %s, %s, %s)""",
            (
                "sess-resume-loop",
                fresh_iso,
                fresh_iso,
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-resume-loop', 'item', 10, 'exclusive', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "sess-resume-loop",
                "--step", "2",
                "--supported-paths", "polish",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "escalate"
        assert data["context"]["escalate_reason"] == "resume_no_progress"
        assert data["context"]["required_path"] == "polish"

    def test_session_offer_resume_progress_does_not_escalate(self, session_offer_db):
        """AC-12 end-to-end: prior checkpoint carrying pre_status != status proves
        the handler advanced the item, so the offer returns resume rather than
        the legacy escalate.

        Replays the chain step 3 shape against the real session-offer
        subprocess entry: the prior polish handler advanced the item
        ``polishing-implementation → implemented`` and wrote a checkpoint with
        ``pre_status=polishing-implementation`` + ``status=implemented``. The
        next offer claims usher on the same ``implemented`` item — the legacy
        same_state heuristic would have fired ESCALATE on the status match;
        the patched detector reads ``pre_status`` from the bridge-mapped
        ``last_completed_step`` dict and routes RESUME because progress was
        made.

        The HTTP route bridge is structurally identical
        (``checkpoint.get('pre_status')``) and is verified in the diff;
        AC-12's "both paths must agree" property holds because both bridges
        drive the same detector through the same dict shape.
        """
        checkpoint = {
            "step": 2,
            "action": "resume",
            "chainable": True,
            "handler_outcome": "completed",
            "item_id": "YOK-10",
            "pre_status": "polishing-implementation",
            "status": "implemented",
            "required_path": "polish",
        }
        conn = connect_test_db(session_offer_db["db_path"])
        fresh_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute("UPDATE items SET status = 'implemented' WHERE id = 10")
        conn.execute(
            f"""INSERT INTO harness_sessions
               (session_id, executor, provider, model, workspace, offered_at, last_heartbeat, offer_envelope)
               VALUES (%s, 'DARIUS', 'anthropic', '{TEST_MODEL_ID}', '/tmp/test', %s, %s, %s)""",
            (
                "sess-resume-progress",
                fresh_iso,
                fresh_iso,
                json.dumps({"max_chain_steps": 3, "chain_checkpoint": checkpoint}),
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (session_id, target_kind, item_id, claim_type, claimed_at, last_heartbeat)
               VALUES ('sess-resume-progress', 'item', 10, 'exclusive', %s, %s)""",
            (fresh_iso, fresh_iso),
        )
        conn.commit()
        conn.close()

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "sess-resume-progress",
                "--step", "3",
                "--supported-paths", "usher",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "resume", (
            f"expected resume but got {data['action']}: {data.get('context')}"
        )
        assert data["context"].get("escalate_reason") is None
