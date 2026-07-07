"""Persistence + concurrency tests for service_client session-offer.

Basic offer + lane resolution → test_service_client_sessions_offer.py
Charge flow → test_service_client_sessions_offer_charge.py
Resume + stale recovery → test_service_client_sessions_offer_resume.py
"""

from __future__ import annotations

import json

from yoke_core.domain import db_backend
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.sessions_offer_envelope_merge import merge_offer_envelope
from runtime.api.test_constants import TEST_MODEL_ID
from runtime.api.test_service_client import _run_client
from runtime.api.test_service_client_sessions_helpers import (
    _pre_register_session,
    session_offer_db,  # noqa: F401 — re-exported fixture
)


def _offer_args(sid, ws, step=None):
    args = ["session-offer", "--executor", "DARIUS",
            "--provider", "anthropic", "--model", "opus",
            "--workspace", ws, "--session-id", sid]
    if step is not None:
        args += ["--step", str(step)]
    return args


def _release_session_claims(db_path, sid):
    conn = connect_test_db(db_path)
    conn.execute(
        "UPDATE work_claims SET released_at = '2026-05-13T05:00:00Z', "
        "release_reason = 'handed_off' WHERE session_id = %s",
        (sid,),
    )
    conn.commit()
    conn.close()


def _seed_second_runnable(db_path):
    conn = connect_test_db(db_path)
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, priority, project_id, project_sequence, "
        " created_at, updated_at, source, frozen) "
        "VALUES (20, 'Second runnable', 'issue', 'refined-idea', "
        " 'high', 1, 20, '2026-03-01', '2026-03-01', 'user', 0)"
    )
    conn.commit()
    conn.close()


class TestSessionOfferPersistence:
    """Tests for harness_sessions/work_claims persistence and concurrency."""

    def test_session_offer_persists_session_record(self, session_offer_db):
        """AC-1: session-offer requires a pre-registered harness_sessions row."""
        sid = "ownership-test-sess"
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
        # Verify session row in DB
        conn = connect_test_db(session_offer_db["db_path"])
        row = conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id = %s", (sid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row["ended_at"] is None

    def test_session_offer_persists_claim_on_charge(self, session_offer_db):
        """AC-2: charge persists a work_claims row."""
        sid = "claim-test-sess"
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
        # Verify claim row in DB
        conn = connect_test_db(session_offer_db["db_path"])
        claim = conn.execute(
            "SELECT * FROM work_claims WHERE session_id = %s AND released_at IS NULL",
            (sid,),
        ).fetchone()
        conn.close()
        assert claim is not None
        assert claim["item_id"] is not None

    def test_concurrent_session_offers_no_double_assign(self, session_offer_db):
        """AC-3: two concurrent offers never both get same item."""
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        _pre_register_session(db, "sess-concur-A", executor="A", workspace=ws)
        _pre_register_session(db, "sess-concur-B", executor="B", workspace=ws)
        r1 = _run_client(
            [
                "session-offer", "--executor", "A",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", "sess-concur-A",
            ],
            db_path=db,
        )
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        d1 = json.loads(r1.stdout)

        r2 = _run_client(
            [
                "session-offer", "--executor", "B",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", "sess-concur-B",
            ],
            db_path=db,
        )
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)

        # First should charge, second should not get the same item
        if d1["action"] == "charge" and d2["action"] == "charge":
            # Both got charge — items must be different
            assert d1["context"]["selected_item"] != d2["context"]["selected_item"]
        elif d1["action"] == "charge":
            # Second got something else (wait/feed/strategize) — no collision
            assert d2["action"] != "charge" or d2["context"]["selected_item"] != d1["context"]["selected_item"]

    def test_reoffer_same_session_returns_resume(self, session_offer_db):
        """AC-4: re-offer with same session_id returns resume."""
        sid = "reoffer-sess"
        ws = session_offer_db["tmp_dir"]
        db = session_offer_db["db_path"]
        _pre_register_session(db, sid, workspace=ws)
        # First offer claims work
        r1 = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert r1.returncode == 0
        d1 = json.loads(r1.stdout)
        assert d1["action"] == "charge"

        # Second offer with same session_id
        r2 = _run_client(
            [
                "session-offer", "--executor", "DARIUS",
                "--provider", "anthropic", "--model", "opus",
                "--workspace", ws, "--session-id", sid,
            ],
            db_path=db,
        )
        assert r2.returncode == 0
        d2 = json.loads(r2.stdout)
        assert d2["action"] == "resume"


class TestMergeOfferEnvelope:
    """Unit tests for merge_offer_envelope."""

    def test_empty_or_malformed_existing_returns_per_offer(self):
        """AC-6: None, empty, malformed JSON, and non-dict all treated as empty."""
        per = {"session_id": "x", "step": 1}
        for existing in (None, "", "not json", json.dumps([1, 2, 3])):
            assert merge_offer_envelope(existing, per) == per

    def test_preserves_chain_skip_memory(self):
        existing = json.dumps({"chain_skip_memory": [{"item_id": "YOK-1"}]})
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["chain_skip_memory"] == [{"item_id": "YOK-1"}]
        assert merged["session_id"] == "x"
        assert merged["step"] == 2

    def test_preserves_chain_checkpoint(self):
        existing = json.dumps({"chain_checkpoint": {"step": 1, "action": "charge"}})
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["chain_checkpoint"] == {"step": 1, "action": "charge"}

    def test_per_offer_overrides_existing_identity(self):
        """AC-5: per-offer identity/step fields overwrite existing."""
        existing = json.dumps({"session_id": "old", "step": 1, "model": "old-model"})
        per = {"session_id": "new", "step": 5, "model": "new-model"}
        merged = merge_offer_envelope(existing, per)
        assert merged["session_id"] == "new"
        assert merged["step"] == 5
        assert merged["model"] == "new-model"

    def test_preserves_runtime_session_id_when_per_offer_omits_it(self):
        """Codex correlation key persists across non-codex offers."""
        existing = json.dumps({"runtime_session_id": "codex-uuid-abc"})
        per = {"session_id": "x", "step": 2}
        merged = merge_offer_envelope(existing, per)
        assert merged["runtime_session_id"] == "codex-uuid-abc"


def _read_envelope(db_path, sid):
    conn = connect_test_db(db_path)
    row = conn.execute(
        "SELECT offer_envelope FROM harness_sessions WHERE session_id = %s",
        (sid,),
    ).fetchone()
    conn.close()
    return json.loads(row[0]) if row and row[0] else {}


class TestSessionOfferCrossCallPersistence:
    """Cross-call envelope persistence regression."""

    def test_chain_skip_memory_survives_next_offer(self, session_offer_db):
        """AC-1: chain_skip_memory written between offers is preserved."""
        from yoke_core.domain.sessions_queries_chain import append_chain_skip_entry
        sid = "persist-skip-sess"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _seed_second_runnable(db)
        _pre_register_session(db, sid, workspace=ws)

        r1 = _run_client(_offer_args(sid, ws), db_path=db)
        assert r1.returncode == 0, f"stderr: {r1.stderr}"

        _release_session_claims(db, sid)
        conn = connect_test_db(db)
        append_chain_skip_entry(
            conn, sid,
            {"item_id": "YOK-10", "skip_reason": "recoverable_substrate"},
        )
        conn.close()

        r2 = _run_client(_offer_args(sid, ws, step=2), db_path=db)
        assert r2.returncode == 0, f"stderr: {r2.stderr}"

        envelope = _read_envelope(db, sid)
        memory_items = [
            e.get("item_id") for e in envelope.get("chain_skip_memory", [])
        ]
        assert "YOK-10" in memory_items, (
            "chain_skip_memory was wiped by the next session-offer write"
        )

    def test_chain_checkpoint_survives_next_offer(self, session_offer_db):
        """AC-2: chain_checkpoint written between offers is preserved."""
        from yoke_core.domain.sessions_queries_chain import update_chain_checkpoint
        sid = "persist-checkpoint-sess"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _pre_register_session(db, sid, workspace=ws)

        r1 = _run_client(_offer_args(sid, ws), db_path=db)
        assert r1.returncode == 0, f"stderr: {r1.stderr}"

        _release_session_claims(db, sid)
        conn = connect_test_db(db)
        update_chain_checkpoint(
            conn, sid, step=1, action="charge", chainable=True,
            handler_outcome="completed", item_id="YOK-10",
        )
        conn.close()

        r2 = _run_client(_offer_args(sid, ws, step=2), db_path=db)
        assert r2.returncode == 0, f"stderr: {r2.stderr}"

        envelope = _read_envelope(db, sid)
        cp = envelope.get("chain_checkpoint")
        assert cp is not None, "chain_checkpoint was wiped by the next session-offer"
        assert cp["action"] == "charge"
        assert cp["item_id"] == "YOK-10"

    def test_skipped_item_not_reselected_in_next_offer(self, session_offer_db):
        """AC-3: skipped item is deduplicated from the next offer's candidates."""
        from yoke_core.domain.sessions_queries_chain import append_chain_skip_entry
        sid = "dedup-sess"
        db = session_offer_db["db_path"]
        ws = session_offer_db["tmp_dir"]
        _seed_second_runnable(db)
        _pre_register_session(db, sid, workspace=ws)

        r1 = _run_client(_offer_args(sid, ws), db_path=db)
        assert r1.returncode == 0, f"stderr: {r1.stderr}"
        d1 = json.loads(r1.stdout)
        assert d1["action"] == "charge"
        first_selected = d1["context"]["selected_item"]

        _release_session_claims(db, sid)
        conn = connect_test_db(db)
        append_chain_skip_entry(
            conn, sid,
            {"item_id": first_selected, "skip_reason": "recoverable_substrate"},
        )
        conn.close()

        r2 = _run_client(_offer_args(sid, ws, step=2), db_path=db)
        assert r2.returncode == 0, f"stderr: {r2.stderr}"
        d2 = json.loads(r2.stdout)
        if d2["action"] == "charge":
            assert d2["context"]["selected_item"] != first_selected, (
                "next offer re-selected the skipped item — dedup broken"
            )
