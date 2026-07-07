"""Regression coverage for the claim-release side of recoverable substrate skips.

When ``/yoke do`` records a ``recoverable_substrate`` chain-skip
checkpoint, the routed handler has already failed before useful work
began. Skip memory carries the dedup key so the next offer avoids the
same item, but the session's item work-claim must also be released --
otherwise the scheduler sees the live claim and resumes the same
unresumable item instead of honoring skip memory.

The peer file ``test_do_loop_recoverable_substrate.py`` covers
skip-memory and ``SchedulerOfferSkipped`` semantics;
``runtime/api/domain/test_sessions_handler_outcome.py`` covers the
helper surfaces. This file is the missing-side coverage for the
claim-release behavior added on top of those.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.test_sessions import _register, conn  # noqa: F401  (Postgres-backed pytest fixture)
from yoke_core.domain.sessions import claim_work
from yoke_core.domain.sessions_handler_outcome import (
    RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP,
    record_recoverable_substrate_skip,
)
from yoke_core.domain.sessions_queries_chain import read_chain_skip_memory


def _seed_item(conn, *, item_id: int, status: str = "implementing") -> None:
    conn.execute(
        """INSERT INTO items
           (id, title, type, status, priority, project_id, project_sequence,
            created_at, updated_at, source, frozen)
           VALUES (%s, %s, 'issue', %s, 'medium', 1, %s,
                   '2026-05-01T00:00:00Z', '2026-05-06T00:00:00Z', 'user', 0)""",
        (item_id, f"Item {item_id}", status, item_id),
    )
    conn.commit()


def _active_item_claim(conn, *, session_id: str, item_id: int):
    return conn.execute(
        """SELECT id, released_at, release_reason FROM work_claims
           WHERE session_id = %s AND target_kind = 'item' AND item_id = %s
           ORDER BY id DESC LIMIT 1""",
        (session_id, item_id),
    ).fetchone()


def _captured_events(captured):
    return [e["name"] for e in captured]


class TestReleasesActiveClaim:
    """AC-1, AC-2: the helper releases the active claim, preserves skip memory."""

    def test_releases_active_claim_and_emits_offer_skipped(self, conn):
        item_id = 9001
        session_id = "substrate-release-session"
        _seed_item(conn, item_id=item_id)
        _register(conn, session_id=session_id)
        claim_work(conn, session_id=session_id, item_id=f"YOK-{item_id}")

        before = _active_item_claim(conn, session_id=session_id, item_id=item_id)
        assert before is not None
        assert before["released_at"] is None

        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{item_id}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{item_id}",
                current_status="implementing",
            )

        # The claim row is now released.
        after = _active_item_claim(conn, session_id=session_id, item_id=item_id)
        assert after is not None
        assert after["released_at"] is not None

        # Skip memory is preserved and carries the failed item in
        # canonical bare-numeric form so scheduler-candidate `YOK-N`
        # comparisons line up after read-side normalization.
        memory = read_chain_skip_memory(conn, session_id)
        assert len(memory) == 1
        assert memory[0]["item_id"] == str(item_id)
        assert entry["item_id"] == str(item_id)
        assert entry["skip_reason"] == "recoverable_substrate"

        # The scheduler event is still emitted.
        assert "SchedulerOfferSkipped" in _captured_events(captured)

    def test_accepts_bare_integer_item_id(self, conn):
        # Bare-numeric input lands in skip memory in the same canonical
        # form as YOK-prefixed input so a recorder that received the
        # bare integer and a scheduler that compared against the
        # YOK-prefixed form always agree.
        item_id = 9002
        session_id = "substrate-bare-int-session"
        _seed_item(conn, item_id=item_id)
        _register(conn, session_id=session_id)
        claim_work(conn, session_id=session_id, item_id=f"YOK-{item_id}")

        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=str(item_id),
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{item_id}",
            )

        row = _active_item_claim(conn, session_id=session_id, item_id=item_id)
        assert row is not None
        assert row["released_at"] is not None
        assert entry["item_id"] == str(item_id)
        memory = read_chain_skip_memory(conn, session_id)
        assert memory[0]["item_id"] == str(item_id)
        assert "SchedulerOfferSkipped" in _captured_events(captured)


class TestReleaseConstantSingleSource:
    """AC-3: the reason-intent value lives in one Python constant."""

    def test_constant_value_is_canonical_intent(self):
        assert RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP == "recoverable-substrate-skip"

    def test_constant_passed_to_release_helper(self, conn):
        item_id = 9003
        session_id = "substrate-constant-session"
        _seed_item(conn, item_id=item_id)
        _register(conn, session_id=session_id)
        claim_work(conn, session_id=session_id, item_id=f"YOK-{item_id}")

        with patch(
            "yoke_core.domain.sessions_lifecycle_release.release_item_claim_for_execution",
        ) as mock_release, patch("yoke_core.domain.events.emit_event"):
            record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{item_id}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{item_id}",
            )

        mock_release.assert_called_once()
        args, _kwargs = mock_release.call_args
        # Positional: (conn, session_id, item_id, reason)
        assert args[3] == RELEASE_REASON_RECOVERABLE_SUBSTRATE_SKIP


class TestReleaseFailureIsNonBlocking:
    """AC-4: release failure must not prevent skip-memory or event emission."""

    def test_release_returning_failure_does_not_block(self, conn):
        # Intruder session never held a claim on the item, so the
        # release attempt returns ``released=False`` (not_owned). The
        # helper must still write skip memory and emit the event.
        item_id = 9004
        session_id = "substrate-no-claim-session"
        _seed_item(conn, item_id=item_id)
        _register(conn, session_id=session_id)

        captured: list[dict] = []
        with patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{item_id}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{item_id}",
            )

        memory = read_chain_skip_memory(conn, session_id)
        assert len(memory) == 1
        assert memory[0]["item_id"] == str(item_id)
        assert "SchedulerOfferSkipped" in _captured_events(captured)

    def test_release_raising_exception_does_not_block(self, conn):
        item_id = 9005
        session_id = "substrate-release-raises-session"
        _seed_item(conn, item_id=item_id)
        _register(conn, session_id=session_id)
        claim_work(conn, session_id=session_id, item_id=f"YOK-{item_id}")

        captured: list[dict] = []
        with patch(
            "yoke_core.domain.sessions_lifecycle_release.release_item_claim_for_execution",
            side_effect=RuntimeError("simulated release failure"),
        ), patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=f"YOK-{item_id}",
                routed_action="advance",
                failure_class="cwd_drift",
                remediation_owner=f"YOK-{item_id}",
            )

        assert entry["item_id"] == str(item_id)
        memory = read_chain_skip_memory(conn, session_id)
        assert len(memory) == 1
        assert "SchedulerOfferSkipped" in _captured_events(captured)


class TestItemIdNoneSkipsRelease:
    """AC-5: ``item_id=None`` keeps existing skip-memory + event flow only."""

    def test_no_release_attempted_when_item_id_is_none(self, conn):
        session_id = "substrate-no-item-session"
        _register(conn, session_id=session_id)

        captured: list[dict] = []
        with patch(
            "yoke_core.domain.sessions_lifecycle_release.release_item_claim_for_execution",
        ) as mock_release, patch(
            "yoke_core.domain.events.emit_event",
            side_effect=lambda name, **kw: captured.append({"name": name, **kw}),
        ):
            entry = record_recoverable_substrate_skip(
                conn,
                session_id=session_id,
                chain_step=1,
                project="yoke",
                item_id=None,
                routed_action="strategize",
                failure_class="process_gate",
                remediation_owner="operator",
            )

        mock_release.assert_not_called()
        assert "item_id" not in entry
        # ``append_chain_skip_entry`` drops entries that carry neither
        # ``item_id`` nor ``process_key``: there is nothing for offer
        # revalidation to dedupe against. The existing flow is preserved
        # and the scheduler event is still emitted.
        memory = read_chain_skip_memory(conn, session_id)
        assert memory == []
        assert "SchedulerOfferSkipped" in _captured_events(captured)
