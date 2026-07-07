"""Focused regressions for offer revalidation, skip memory, and chain accounting.

This module reproduces the three concrete failure shapes the ticket spec
calls out and verifies the substrate that prevents them:

* live-claim conflict skip + within-chain skip memory
* stale lifecycle skip before claim acquisition
* SchedulerOfferSkipped audit emission

The tests exercise the helper surface in
:mod:`yoke_core.domain.sessions_offer_revalidation` plus the chain-skip
memory helpers in :mod:`yoke_core.domain.sessions_queries_chain` directly,
so they do not depend on the full HTTP/CLI offer path or scheduler fixtures.
"""

from __future__ import annotations

import pytest
from unittest.mock import patch

from runtime.api.test_sessions import _register, conn  # noqa: F401  (Postgres-backed pytest fixture)
from yoke_core.domain.sessions import (
    append_chain_skip_entry,
    claim_work,
    read_chain_skip_memory,
)
from yoke_core.domain.sessions_offer_revalidation import (
    holder_session_for_item,
    record_offer_skip,
    revalidate_candidate_status,
)


def _seed_item(conn, *, item_id: int, status: str, project: str = "yoke") -> None:
    """Insert a minimum-viable item row for revalidation queries."""
    project_id = 1 if project == "yoke" else 2
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (%s, %s, 'issue', %s, 'medium', %s, %s,
                   '2026-05-01T00:00:00Z', '2026-05-06T00:00:00Z', 'user', 0)""",
        (item_id, f"Item {item_id}", status, project_id, item_id),
    )
    conn.commit()


class TestRevalidateCandidateStatus:
    """AC-1 / AC-2: stale-lifecycle skip before claim acquisition."""

    def test_returns_true_when_status_unchanged(self, conn):
        _seed_item(conn, item_id=2001, status="reviewed-implementation")
        valid, current = revalidate_candidate_status(
            conn, item_id=f"YOK-{2001}", expected_status="reviewed-implementation",
        )
        assert valid is True
        assert current == "reviewed-implementation"

    def test_returns_false_when_status_advanced(self, conn):
        """Scheduler offered POLISH at status=polishing-implementation,
        but another actor moved the item to ``implemented`` between schedule
        computation and claim acquisition. Revalidation must catch this."""
        _seed_item(conn, item_id=2002, status="implemented")
        valid, current = revalidate_candidate_status(
            conn, item_id=f"YOK-{2002}", expected_status="polishing-implementation",
        )
        assert valid is False
        assert current == "implemented"

    def test_returns_false_when_item_missing(self, conn):
        valid, current = revalidate_candidate_status(
            conn, item_id=f"YOK-{9998}", expected_status="refined-idea",
        )
        assert valid is False
        assert current is None

    def test_accepts_bare_integer_and_sun_prefix(self, conn):
        _seed_item(conn, item_id=2003, status="implementing")
        valid_a, _ = revalidate_candidate_status(
            conn, item_id=f"YOK-{2003}", expected_status="implementing",
        )
        valid_b, _ = revalidate_candidate_status(
            conn, item_id="2003", expected_status="implementing",
        )
        assert valid_a is True
        assert valid_b is True


class TestHolderSessionForItem:
    """AC-11: skip events surface holder identity for live-claim conflicts."""

    def test_returns_holder_context_when_claimed(self, conn):
        _seed_item(conn, item_id=3001, status="implementing")
        _register(conn, session_id="holder-sess")
        claim = claim_work(conn, session_id="holder-sess", item_id=f"YOK-{3001}")
        ctx = holder_session_for_item(conn, f"YOK-{3001}")
        assert ctx["holder_session_id"] == "holder-sess"
        assert ctx["claim_id"] == claim["id"]
        assert ctx.get("claimed_at")

    def test_returns_holder_unknown_when_no_claim(self, conn):
        _seed_item(conn, item_id=3002, status="implementing")
        ctx = holder_session_for_item(conn, f"YOK-{3002}")
        assert ctx == {"holder_unknown": True}


class TestChainSkipMemory:
    """AC-4: within-chain skip memory deduplicates re-offers."""

    def test_empty_memory_for_fresh_session(self, conn):
        _register(conn, session_id="skip-fresh")
        assert read_chain_skip_memory(conn, "skip-fresh") == []

    def test_append_persists_and_round_trips(self, conn):
        _register(conn, session_id="skip-rt")
        append_chain_skip_entry(
            conn, "skip-rt",
            {"item_id": f"YOK-{4001}", "skip_reason": "stale_lifecycle", "chain_step": 1},
        )
        append_chain_skip_entry(
            conn, "skip-rt",
            {"item_id": f"YOK-{4002}", "skip_reason": "live_claim_conflict", "chain_step": 1},
        )
        memory = read_chain_skip_memory(conn, "skip-rt")
        assert [e["item_id"] for e in memory] == [f"YOK-{4001}", f"YOK-{4002}"]
        assert memory[0]["skip_reason"] == "stale_lifecycle"
        assert memory[1]["skip_reason"] == "live_claim_conflict"

    def test_entry_without_item_or_process_is_ignored(self, conn):
        _register(conn, session_id="skip-noid")
        append_chain_skip_entry(
            conn, "skip-noid",
            {"skip_reason": "process_disabled_by_config"},
        )
        assert read_chain_skip_memory(conn, "skip-noid") == []


class TestRecordOfferSkip:
    """AC-4 / AC-11: skip helper persists memory entry AND emits audit event."""

    def test_stale_lifecycle_skip_persists_and_emits(self, conn):
        _register(conn, session_id="skip-emit-stale")
        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            record_offer_skip(
                conn,
                session_id="skip-emit-stale",
                item_id=f"YOK-{5001}",
                skip_reason="stale_lifecycle",
                chain_step=2,
                project="yoke",
                expected_status="polishing-implementation",
                current_status="implemented",
                expected_next_step="polish",
            )
        memory = read_chain_skip_memory(conn, "skip-emit-stale")
        assert len(memory) == 1
        assert memory[0]["item_id"] == f"YOK-{5001}"
        assert memory[0]["skip_reason"] == "stale_lifecycle"
        assert memory[0]["expected_status"] == "polishing-implementation"
        assert memory[0]["current_status"] == "implemented"
        assert memory[0]["chain_step"] == 2

        events = [c for c in captured if c["name"] == "SchedulerOfferSkipped"]
        assert len(events) == 1
        ctx = events[0]["context"]
        assert ctx["session_id"] == "skip-emit-stale"
        assert ctx["item_id"] == f"YOK-{5001}"
        assert ctx["skip_reason"] == "stale_lifecycle"
        assert ctx["chain_step"] == 2
        assert ctx["current_status"] == "implemented"
        assert ctx["recommended_action"] == "polish"

    def test_live_claim_conflict_carries_holder_identity(self, conn):
        _register(conn, session_id="skip-emit-claim")
        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            record_offer_skip(
                conn,
                session_id="skip-emit-claim",
                item_id=f"YOK-{5002}",
                skip_reason="live_claim_conflict",
                chain_step=1,
                project="yoke",
                expected_status="implementing",
                current_status="implementing",
                expected_next_step="advance",
                holder_context={
                    "holder_session_id": "rival-sess",
                    "claim_id": 901,
                    "claimed_at": "2026-05-06T17:00:00Z",
                },
            )
        events = [c for c in captured if c["name"] == "SchedulerOfferSkipped"]
        assert len(events) == 1
        ctx = events[0]["context"]
        assert ctx["claim_holder_session_id"] == "rival-sess"
        assert ctx["claim_id"] == 901
        assert ctx["claimed_at"] == "2026-05-06T17:00:00Z"
        assert ctx["skip_reason"] == "live_claim_conflict"

        memory = read_chain_skip_memory(conn, "skip-emit-claim")
        assert memory[0]["claim_holder_session_id"] == "rival-sess"
        assert memory[0]["claim_id"] == 901

    def test_holder_unknown_falls_through_to_extra_context(self, conn):
        _register(conn, session_id="skip-emit-unknown")
        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            record_offer_skip(
                conn,
                session_id="skip-emit-unknown",
                item_id=f"YOK-{5003}",
                skip_reason="live_claim_conflict",
                chain_step=2,
                project="yoke",
                expected_status="implementing",
                current_status="implementing",
                expected_next_step="advance",
                holder_context={"holder_unknown": True},
            )
        events = [c for c in captured if c["name"] == "SchedulerOfferSkipped"]
        assert len(events) == 1
        ctx = events[0]["context"]
        assert ctx.get("holder_unknown") is True
