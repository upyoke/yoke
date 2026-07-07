"""TestReleaseItemClaimForExecution: AC-7 atomic release+focus-clear."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from runtime.api.test_sessions import _register, conn  # noqa: F401  (pytest fixture)
from runtime.api.test_dependency_schema import ITEMS_SCHEMA
from yoke_core.domain.sessions import (
    EVENT_WORK_RELEASED,
    claim_work,
)
from runtime.api.sessions_api_stale_test_helpers import (
    _now_literal,
    apply_ddl_statements,
)


def _sun(item_id: int) -> str:
    return f"YOK-{item_id}"


class TestReleaseItemClaimForExecution:
    """AC-7: execution-owned atomic release+focus-clear."""

    def test_releases_and_clears_focus_together(self, conn):
        from yoke_core.domain.sessions import release_item_claim_for_execution

        _register(conn, session_id="exec-sess")
        claim_work(conn, session_id="exec-sess", item_id=_sun(500))

        # Precondition: current_item set by claim_work
        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id='exec-sess'",
        ).fetchone()
        assert row["current_item_id"] == "500"

        result = release_item_claim_for_execution(
            conn, "exec-sess", _sun(500), "finalize-exit",
        )
        assert result["released"] is True
        # Caller intent preserved
        assert result["reason_intent"] == "finalize-exit"
        # Schema-valid enum stored
        assert result["reason_stored"] == "released"

        # current_item cleared
        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id='exec-sess'",
        ).fetchone()
        assert row["current_item_id"] is None

        # claim released with canonical enum (CHECK constraint)
        claim_row = conn.execute(
            "SELECT released_at, release_reason FROM work_claims "
            "WHERE session_id='exec-sess' AND item_id='500'",
        ).fetchone()
        assert claim_row["released_at"] is not None
        assert claim_row["release_reason"] == "released"

    def test_maps_handoff_intents_to_handed_off(self, conn):
        """Custom intent strings map to the schema enum."""
        from yoke_core.domain.sessions import release_item_claim_for_execution

        _register(conn, session_id="handoff-sess")
        claim_work(conn, session_id="handoff-sess", item_id=_sun(510))
        result = release_item_claim_for_execution(
            conn, "handoff-sess", _sun(510), "handoff-to-polish",
        )
        assert result["reason_intent"] == "handoff-to-polish"
        assert result["reason_stored"] == "handed_off"
        claim_row = conn.execute(
            "SELECT release_reason FROM work_claims "
            "WHERE session_id='handoff-sess' AND item_id='510'",
        ).fetchone()
        assert claim_row["release_reason"] == "handed_off"

    def test_completed_release_rejected_while_item_is_still_active(self, conn):
        from yoke_core.domain.sessions import release_item_claim_for_execution

        apply_ddl_statements(conn, ITEMS_SCHEMA)
        _ts = _now_literal()
        conn.execute(
            "INSERT INTO items (id, title, status, created_at, updated_at)"
            " VALUES (530, 'Polish item', 'polishing-implementation', %s, %s)",
            (_ts, _ts),
        )
        _register(conn, session_id="active-status-sess")
        claim_work(conn, session_id="active-status-sess", item_id=_sun(530))

        with pytest.raises(ValueError, match="polishing-implementation"):
            release_item_claim_for_execution(
                conn, "active-status-sess", _sun(530), "completed",
            )

        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id='active-status-sess'",
        ).fetchone()
        assert row["current_item_id"] == "530"
        claim_row = conn.execute(
            "SELECT released_at FROM work_claims "
            "WHERE session_id='active-status-sess' AND item_id='530'",
        ).fetchone()
        assert claim_row["released_at"] is None

    def test_completed_release_allows_successful_handoff_status(self, conn):
        from yoke_core.domain.sessions import release_item_claim_for_execution

        apply_ddl_statements(conn, ITEMS_SCHEMA)
        _ts = _now_literal()
        conn.execute(
            "INSERT INTO items (id, title, status, created_at, updated_at)"
            " VALUES (531, 'Implemented item', 'implemented', %s, %s)",
            (_ts, _ts),
        )
        _register(conn, session_id="implemented-sess")
        claim_work(conn, session_id="implemented-sess", item_id=_sun(531))

        result = release_item_claim_for_execution(
            conn, "implemented-sess", _sun(531), "completed",
        )
        assert result["released"] is True
        assert result["reason_stored"] == "completed"

    def test_no_claim_is_noop(self, conn):
        from yoke_core.domain.sessions import release_item_claim_for_execution
        from yoke_core.domain.sessions_lifecycle_release_failure import (
            RELEASE_FAILURE_ITEM_NOT_FOUND,
        )

        _register(conn, session_id="empty-sess")
        result = release_item_claim_for_execution(
            conn, "empty-sess", _sun(999), "handoff-to-usher",
        )
        assert result["released"] is False
        # This fixture has no claim row for the requested item, so the
        # diagnose path returns item_not_found.
        assert result["failure_reason"] == RELEASE_FAILURE_ITEM_NOT_FOUND
        assert result["holder_session_id"] is None
        assert result["reason_intent"] == "handoff-to-usher"

    def test_does_not_clear_focus_pointing_at_other_item(self, conn):
        from yoke_core.domain.sessions import (
            release_item_claim_for_execution,
            set_current_item,
        )

        _register(conn, session_id="multi-sess")
        claim_work(conn, session_id="multi-sess", item_id=_sun(700))
        # Focus currently points at the claimed item because claim_work set it.
        # Move focus to a different item manually (simulating attribution
        # mutation path that points elsewhere).
        set_current_item(conn, "multi-sess", _sun(800))

        release_item_claim_for_execution(
            conn, "multi-sess", _sun(700), "finalize-exit",
        )

        # Focus on the earlier item stays -- we did not release a claim for it.
        row = conn.execute(
            "SELECT current_item_id FROM harness_sessions WHERE session_id='multi-sess'",
        ).fetchone()
        assert row["current_item_id"] == "800"

    def test_generic_attribution_helpers_are_not_claim_owning(self, conn):
        """AC-7: set_current_item / clear_current_item MUST stay attribution-only."""
        from yoke_core.domain.sessions import (
            clear_current_item,
            set_current_item,
        )

        _register(conn, session_id="attr-sess")
        claim_work(conn, session_id="attr-sess", item_id=_sun(900))
        # set_current_item should not release the claim.
        set_current_item(conn, "attr-sess", _sun(901))
        claim_row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id='attr-sess' AND item_id='900'",
        ).fetchone()
        assert claim_row["released_at"] is None
        # clear_current_item should not release the claim either.
        clear_current_item(conn, "attr-sess")
        claim_row = conn.execute(
            "SELECT released_at FROM work_claims WHERE session_id='attr-sess' AND item_id='900'",
        ).fetchone()
        assert claim_row["released_at"] is None

    @patch("yoke_core.domain.sessions_analytics._emit_event")
    def test_offer_override_stores_canonical_reason_and_intent(self, mock_emit, conn):
        """AC-5: offer-override maps to 'released' enum, preserves intent in event."""
        from yoke_core.domain.sessions import release_item_claim_for_execution

        _register(conn, session_id="offer-ovr-sess")
        claim_work(conn, session_id="offer-ovr-sess", item_id=_sun(520))
        result = release_item_claim_for_execution(
            conn, "offer-ovr-sess", _sun(520), "offer-override",
        )
        assert result["released"] is True
        assert result["reason_intent"] == "offer-override"
        assert result["reason_stored"] == "released"

        # DB stores canonical enum
        claim_row = conn.execute(
            "SELECT release_reason FROM work_claims "
            "WHERE session_id='offer-ovr-sess' AND item_id='520'",
        ).fetchone()
        assert claim_row["release_reason"] == "released"

        # WorkReleased event preserves offer-override intent
        wr_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == EVENT_WORK_RELEASED
        ]
        assert len(wr_calls) == 1
        ctx = wr_calls[0][1]["context"]
        assert ctx["release_reason_intent"] == "offer-override"
        assert ctx["release_reason"] == "released"
        assert ctx["execution_owned"] is True
