"""Tests for service_client.py session-offer claim reconciliation and decoupling."""

from __future__ import annotations

import json

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import session_offer_db, _pre_register_session  # noqa: F401
from runtime.api.test_constants import TEST_MODEL_ID


# ---------------------------------------------------------------------------
# offer-time claim reconciliation tests
# ---------------------------------------------------------------------------


class TestOfferClaimReconciliation:
    """eager offer-time claims are released when decision is not charge."""

    def test_session_offer_strategize_releases_eager_claim(self, session_offer_db, monkeypatch, capsys):
        """AC-4: non-charge decision releases the eager offer-time claim.

        When session_offer_with_ownership() creates a claim and
        decide_next_action() chooses strategize (not charge), the claim must
        be released before NextActionChosen is emitted.
        """
        import yoke_core.api.service_client as service_client
        from yoke_core.domain.session import ActionKind, NextAction

        sid = "strategize-release-sess"
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])
        monkeypatch.setenv("YOKE_DB", db)

        def _force_strategize(offer, frontier, claims, **kwargs):
            return NextAction(
                action=ActionKind.STRATEGIZE,
                reason="Drift review: both SML and frontier impacted.",
                chainable=False,
                correlation_id=offer.session_id,
                context={"trigger": "drift_review"},
            )

        monkeypatch.setattr(service_client, "decide_next_action", _force_strategize)

        rc = service_client.cmd_session_offer([
            "--executor", "DARIUS",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert rc == 0, f"stderr: {captured.err}"
        assert data["action"] == "strategize", f"expected strategize, got {data['action']}"

        # Verify no unreleased claims remain for this session
        conn = connect_test_db(db)
        active_claims = conn.execute(
            "SELECT * FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchall()
        events = conn.execute(
            "SELECT event_name, envelope FROM events WHERE session_id = %s ORDER BY id",
            (sid,),
        ).fetchall()
        # Verify the released claim has offer-override reason
        released_claims = conn.execute(
            "SELECT * FROM work_claims WHERE session_id = %s AND released_at IS NOT NULL",
            (sid,),
        ).fetchall()
        conn.close()
        assert len(active_claims) == 0, (
            f"Expected 0 active claims after strategize override, "
            f"found {len(active_claims)}: {[dict(c) for c in active_claims]}"
        )
        assert len(released_claims) >= 1, "Expected at least 1 released claim"
        assert released_claims[0]["release_reason"] == "released"
        event_names = [row["event_name"] for row in events]
        assert "WorkReleased" in event_names
        assert "NextActionChosen" in event_names
        assert event_names.index("WorkReleased") < event_names.index("NextActionChosen")

        release_event = next(
            json.loads(row["envelope"]) for row in events if row["event_name"] == "WorkReleased"
        )
        assert release_event["context"]["release_reason_intent"] == "offer-override"
        assert release_event["context"]["release_reason"] == "released"

    def test_session_offer_charge_keeps_claim(self, session_offer_db):
        """AC-6: charge-winning path still keeps its claim."""
        sid = "charge-keeps-claim-sess"
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] == "charge"

        # Verify claim IS still active (not released by reconciliation)
        conn = connect_test_db(db)
        active_claims = conn.execute(
            "SELECT * FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchall()
        event_names = [
            row["event_name"]
            for row in conn.execute(
                "SELECT event_name FROM events WHERE session_id = %s ORDER BY id",
                (sid,),
            ).fetchall()
        ]
        conn.close()
        assert len(active_claims) == 1, (
            f"Expected 1 active claim after charge, found {len(active_claims)}"
        )
        assert "WorkReleased" not in event_names


# ---------------------------------------------------------------------------
# session-offer decoupling tests (task 004)
# ---------------------------------------------------------------------------


class TestSessionOfferDecoupling:
    """session-offer requires pre-registered session, no self-registration."""

    def test_session_offer_no_session_returns_error(self, session_offer_db):
        """AC-2: session-offer without pre-registered session fails with NO_SESSION."""
        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", "nonexistent-session",
            ],
            db_path=session_offer_db["db_path"],
        )
        assert result.returncode == 1
        assert "No active session found" in result.stderr
        assert "nonexistent-session" in result.stderr

    def test_session_offer_ended_session_returns_error(self, session_offer_db):
        """AC-3: session-offer with ended session fails with SESSION_ENDED."""
        sid = "ended-offer-session"
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])
        # End the session
        _run_client(["session-end", "--session-id", sid], db_path=db)

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=db,
        )
        assert result.returncode == 1
        assert "has ended" in result.stderr
        assert sid in result.stderr

    def test_session_offer_with_active_session_succeeds(self, session_offer_db):
        """AC-1: session-offer with pre-registered active session succeeds."""
        sid = "active-session-ok"
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])

        result = _run_client(
            [
                "session-offer",
                "--executor", "DARIUS",
                "--provider", "anthropic",
                "--model", TEST_MODEL_ID,
                "--workspace", session_offer_db["tmp_dir"],
                "--session-id", sid,
            ],
            db_path=db,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        data = json.loads(result.stdout)
        assert data["action"] in ("charge", "feed", "strategize", "escalate", "wait")

    def test_session_offer_no_longer_calls_register_session(self, session_offer_db, monkeypatch):
        """AC-4: session-offer must not call register_session()."""
        import yoke_core.domain.sessions as sessions_mod

        _original_register = sessions_mod.register_session
        called = []

        def _spy(*args, **kwargs):
            called.append(True)
            return _original_register(*args, **kwargs)

        monkeypatch.setattr(sessions_mod, "register_session", _spy)

        sid = "no-register-check"
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=session_offer_db["tmp_dir"])
        monkeypatch.setenv("YOKE_DB", db)

        import yoke_core.api.service_client as sc
        sc.cmd_session_offer([
            "--executor", "DARIUS",
            "--provider", "anthropic",
            "--model", TEST_MODEL_ID,
            "--workspace", session_offer_db["tmp_dir"],
            "--session-id", sid,
        ])
        assert len(called) == 0, "register_session() was called — session-offer should not register"
